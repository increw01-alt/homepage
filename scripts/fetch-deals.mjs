// 상품권 실시간 할인 딜 수집 — 11번가 오픈API(상품검색)에서 판매가를 받아
// 액면가 대비 할인율을 계산해 html/deals.json 을 생성합니다.
//
// 필요 환경변수(GitHub Actions Secret):
//   ST11_API_KEY       11번가 오픈API 인증키 (필수)
//   LINKPRICE_AFF_ID   링크프라이스 제휴 ID (선택 — 있으면 링크를 제휴추적링크로 감쌉니다)
//
// 로컬에 node 가 없어도 GitHub Actions(Node 20)에서 실행됩니다.
import { getText, writeJSON, nowKSTLabel } from './lib.mjs';

const OUT = 'html/deals.json';
const API_KEY = process.env.ST11_API_KEY || '';
const LINKPRICE_AFF_ID = process.env.LINKPRICE_AFF_ID || '';

// 링크프라이스 머천드 코드(제휴 승인된 몰만) — 승인 후 실제 코드로 채우세요.
const LINKPRICE_MERCHANT = {
  '11번가': '', // 예: 'A100612345'
};

/** 수집 대상: 요약표 컬럼(col) + 카테고리 제목(category) + 검색어(keyword) + 상품명 매칭(match) */
const CATEGORIES = [
  { col: '문화', category: '컬쳐랜드 문화상품권', keyword: '컬쳐랜드 문화상품권', match: /컬쳐랜드|컬처랜드|문화상품권/ },
  { col: '도서', category: '도서문화상품권 (북앤라이프)', keyword: '북앤라이프 도서문화상품권', match: /도서문화|북앤라이프/ },
  { col: '롯데', category: '롯데 상품권', keyword: '롯데상품권 모바일교환권', match: /롯데/ },
  { col: '현대', category: '현대백화점 상품권', keyword: '현대백화점 상품권', match: /현대/ },
  { col: '신세계', category: '신세계 상품권', keyword: '신세계상품권', match: /신세계|이마트/ },
];

const PER_CATEGORY = 5; // 카테고리별 노출 딜 개수

// ---------- XML 유틸(의존성 없이 정규식으로) ----------
const stripCData = (s) => s.replace(/^<!\[CDATA\[/, '').replace(/\]\]>$/, '');
function tag(block, name) {
  const m = block.match(new RegExp(`<${name}>([\\s\\S]*?)</${name}>`, 'i'));
  return m ? stripCData(m[1]).trim() : '';
}
function products(xml) {
  return [...xml.matchAll(/<Product>([\s\S]*?)<\/Product>/gi)].map((m) => m[1]);
}

/** 상품명에서 액면가 추출: "5만원권" → 50000, "50만원" → 500000 */
function parseFace(name) {
  const m = name.match(/(\d+)\s*만\s*원/);
  return m ? Number(m[1]) * 10000 : null;
}

/** 할인율 계산이 말이 되는 가격인지(액면가의 80~100%) — 오기·비상품권 제거 */
function saneRate(price, face) {
  if (!Number.isFinite(price) || price <= 0) return false;
  const rate = ((face - price) / face) * 100;
  return rate >= 0.1 && rate <= 20;
}

/** 링크프라이스 제휴 딥링크로 감싸기(설정 없으면 원본 URL 그대로) */
function affiliateUrl(rawUrl, sellerName) {
  const m = LINKPRICE_MERCHANT[sellerName];
  if (!LINKPRICE_AFF_ID || !m || !rawUrl) return rawUrl;
  return `https://click.linkprice.com/click.php?m=${m}&a=${LINKPRICE_AFF_ID}&l=9999&tu=${encodeURIComponent(rawUrl)}`;
}

// ---------- 11번가 상품검색 ----------
async function search11st(keyword) {
  const url =
    'http://openapi.11st.co.kr/openapi/OpenApiService.tmall' +
    `?key=${encodeURIComponent(API_KEY)}` +
    '&apiCode=ProductSearch' +
    `&keyword=${encodeURIComponent(keyword)}` +
    '&pageSize=50';
  const xml = await getText(url);
  return products(xml)
    .map((b) => {
      const name = tag(b, 'ProductName');
      const price = Number(tag(b, 'ProductPrice').replace(/[^\d]/g, ''));
      const code = tag(b, 'ProductCode');
      const detail = tag(b, 'DetailPageUrl') || (code ? `https://www.11st.co.kr/products/${code}` : '#');
      return { name, price, url: detail };
    })
    .filter((p) => p.name && Number.isFinite(p.price) && p.price > 0);
}

/** 한 카테고리의 11번가 딜 목록(할인율 내림차순) */
async function collectCategory(cat) {
  const raw = await search11st(cat.keyword);
  const deals = [];
  for (const p of raw) {
    if (!cat.match.test(p.name)) continue;
    const face = parseFace(p.name);
    if (!face || !saneRate(p.price, face)) continue;
    const rate = Math.round(((face - p.price) / face) * 1000) / 10; // 소수 첫째자리
    deals.push({ seller: '11번가', rate, title: p.name, url: affiliateUrl(p.url, '11번가') });
  }
  // 할인율 내림차순, 상위 N개
  deals.sort((a, b) => b.rate - a.rate);
  return deals.slice(0, PER_CATEGORY);
}

// ---------- 실행 ----------
async function main() {
  if (!API_KEY) throw new Error('ST11_API_KEY 환경변수가 없습니다. GitHub Actions Secret에 11번가 오픈API 키를 등록하세요.');

  const dealsByCat = [];
  let okCount = 0;
  for (const cat of CATEGORIES) {
    try {
      const items = await collectCategory(cat);
      if (items.length) okCount++;
      dealsByCat.push({ category: cat.category, col: cat.col, items });
      console.log(`${cat.category}: ${items.length}건`);
    } catch (err) {
      dealsByCat.push({ category: cat.category, col: cat.col, items: [] });
      console.error(`${cat.category} 실패: ${err.message || err}`);
    }
    await new Promise((r) => setTimeout(r, 700)); // API 배려
  }

  if (!okCount) throw new Error('모든 카테고리 수집 실패 — deals.json 을 갱신하지 않습니다(기존 데이터 유지).');

  // 요약표: 현재는 11번가 단일 판매처. 소스가 늘면 rows 를 추가하면 됩니다.
  const columns = CATEGORIES.map((c) => c.col);
  const bestRates = dealsByCat.map((g) => (g.items.length ? g.items[0].rate : null));

  const data = {
    updated_at: nowKSTLabel(),
    note: '본 페이지의 딜 정보는 11번가 등 공개 오픈마켓의 판매가를 한국상품권협회가 수집해 액면가 대비 할인율로 자동 계산합니다. 일부 링크는 제휴마케팅이 포함되어 수수료를 지급받을 수 있습니다.',
    summary: {
      columns,
      rows: [{ seller: '11번가', rates: bestRates }],
    },
    deals: dealsByCat.map((g) => ({ category: g.category, items: g.items })),
  };

  await writeJSON(OUT, data);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
