"""검색 메타데이터, 날짜, sitemap 및 화면/FAQ 일치 회귀 테스트."""
import contextlib
import copy
import io
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import collect_deals as cd
import collect_rates as cr


def ld(fragment):
    return json.loads(re.search(r'<script[^>]*>(.*?)</script>', fragment, re.S)[1])


def plain(value):
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]+>', '', value))).strip()


class TestSeoPrerender(unittest.TestCase):
    def setUp(self):
        self.deals = json.loads((ROOT / 'html/deals.json').read_text(encoding='utf-8'))
        self.rates = json.loads((ROOT / 'html/rates.json').read_text(encoding='utf-8'))

    def test_collection_preserves_itemlist_and_refreshes_timestamp(self):
        for timestamp in ('2026-11-19 06:09', '2026-11-19 07:09'):
            self.deals['updated_at'] = timestamp
            graph = ld(cd.build_prerender(self.deals)['jsonld'])['@graph']
            collection, items = graph
            self.assertEqual(collection['@type'], 'CollectionPage')
            self.assertEqual(collection['dateModified'], timestamp.replace(' ', 'T') + ':00+09:00')
            self.assertEqual(collection['publisher']['@type'], 'Organization')
            self.assertEqual(collection['isPartOf']['@type'], 'WebSite')
            self.assertEqual(items['@type'], 'ItemList')
            self.assertEqual(items['numberOfItems'], min(10, sum(len(g['items']) for g in self.deals['deals'])))

    def test_dataset_iso_date_and_price_basis(self):
        self.rates['updated_at'] = '2026-11-19 06:09'
        parts = cr.build_prerender(self.rates)
        data = ld(parts['ratesJsonld'])
        self.assertEqual(data['dateModified'], '2026-11-19T06:09:00+09:00')
        self.assertEqual(datetime.fromisoformat(data['dateModified']).utcoffset(), timedelta(hours=9))
        self.assertIn('10만원권 최저 살때', data['description'])
        self.assertIn(data['description'], unescape(parts['ratesMetaDesc']))
        self.assertEqual([v['name'] for v in data['variableMeasured']], ['살때 가격', '팔때 가격'])
        self.assertTrue(all('10만원권' in v['description'] for v in data['variableMeasured']))

    def test_dates_convert_timezone_and_omit_unknown_values(self):
        for module in (cd, cr):
            self.assertEqual(module.iso_modified_date('2026-11-18T21:09:00Z'), '2026-11-19T06:09:00+09:00')
            for value in (None, '', 'unknown'):
                self.assertIsNone(module.iso_modified_date(value))
        self.assertNotIn('dateModified', ld(cr.build_prerender({})['ratesJsonld']))
        self.assertNotIn('dateModified', ld(cd.build_prerender({})['jsonld'])['@graph'][0])

    def test_empty_descriptions_have_no_fabricated_prices(self):
        deal_text = '컬쳐랜드 문화상품권·도서문화상품권·백화점 상품권 할인 딜을 신뢰할 수 있는 판매처에서만 골라 한국상품권협회가 매시간 집계합니다.'
        rate_text = '신세계·롯데·현대·갤러리아·AK 백화점 상품권의 살때·팔때 시세를 한국상품권협회가 매시간 집계하고 검증합니다.'
        self.assertEqual(cd.build_prerender({})['metaDesc'], f'<meta name="description" content="{deal_text}">')
        self.assertEqual(cr.build_prerender({})['ratesMetaDesc'], f'<meta name="description" content="{rate_text}">')

    def test_rate_description_orders_brands_and_omits_missing_prices(self):
        self.rates['summary'] = list(reversed(self.rates['summary']))
        for row in self.rates['summary']:
            if row['brand'] == '롯데':
                row['bestBuy'] = None
        desc = ld(cr.build_prerender(self.rates)['ratesJsonld'])['description'].split('. ')[0]
        self.assertLess(desc.index('신세계'), desc.index('현대'))
        self.assertNotIn('롯데', desc)

    def test_deal_external_titles_cannot_close_json_script(self):
        data = copy.deepcopy(self.deals)
        data['deals'][0]['items'][0]['title'] = '</script><!--PR:jsonld--><script>'
        fragment = cd.build_prerender(data)['jsonld']
        self.assertEqual(fragment.count('</script>'), 1)
        self.assertNotIn('<!--PR:', fragment)
        self.assertIn('</script>', json.dumps(ld(fragment), ensure_ascii=False))


class TestRateSitemap(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'tests')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'sitemap.xml'
        self.original = (ROOT / 'html/sitemap.xml').read_bytes()
        self.path.write_bytes(self.original)
        self.patcher = patch.object(cr, 'SITEMAP_PATH', str(self.path))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.target = re.compile(rb'(<loc>https://koreagiftcard\.co\.kr/%EC%83%81%ED%92%88%EA%B6%8C%EC%8B%9C%EC%84%B8</loc>\s*<lastmod>)([^<]*)(</lastmod>)')

    def test_updates_only_target_and_skips_second_write(self):
        stale = self.target.sub(rb'\g<1>2000-01-01\g<3>', self.original)
        self.path.write_bytes(stale)
        self.assertTrue(cr.update_sitemap_lastmod())
        today = datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d').encode()
        self.assertEqual(self.path.read_bytes(), self.target.sub(lambda m: m[1] + today + m[3], stale))
        with patch('builtins.open', wraps=open) as opened:
            self.assertFalse(cr.update_sitemap_lastmod())
            self.assertFalse(any(len(c.args) > 1 and 'w' in c.args[1] for c in opened.call_args_list))

    def test_missing_target_warns_and_preserves_file(self):
        self.path.write_text('<urlset/>', encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertFalse(cr.update_sitemap_lastmod())
        self.assertIn('::warning::', output.getvalue())
        self.assertEqual(self.path.read_text(encoding='utf-8'), '<urlset/>')

    def test_unreadable_sitemap_warns_without_crashing(self):
        with patch.object(cr, 'SITEMAP_PATH', str(Path(self.temp.name) / 'missing.xml')):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertFalse(cr.update_sitemap_lastmod())
            self.assertIn('::warning::', output.getvalue())


class TestVisibleSeo(unittest.TestCase):
    def test_all_jsonld_parse_and_faq_answers_match_screen(self):
        for page, expected in [('상품권딜', 22), ('상품권시세', 21)]:
            source = (ROOT / 'html' / (page + '.html')).read_text(encoding='utf-8')
            blocks = [json.loads(x) for x in re.findall(r'<script type="application/ld\+json">(.*?)</script>', source, re.S)]
            faq = next(x for x in blocks if x.get('@type') == 'FAQPage')['mainEntity']
            visible = re.findall(r'<details class="faq_item">\s*<summary>(.*?)</summary>\s*<p class="faq_a">(.*?)</p>\s*</details>', source, re.S)
            self.assertEqual(len(visible), expected)
            self.assertEqual([(x['name'], x['acceptedAnswer']['text']) for x in faq], [(plain(q), plain(a)) for q, a in visible])
            self.assertEqual(len(re.findall(r'<h1\b', source)), 1)
            self.assertTrue(all(re.search(r'\balt\s*=', tag) for tag in re.findall(r'<img\b[^>]*>', source)))

    def test_rate_intro_precedes_hero_picture_and_note_is_not_overwritten(self):
        source = (ROOT / 'html/상품권시세.html').read_text(encoding='utf-8')
        self.assertRegex(source, r'</h1>\s*<p class="kgc-market-intro">백화점 상품권 시세는')
        self.assertLess(source.index('<p class="kgc-market-intro">'), source.index('<div class="kgc-vouchers"'))
        self.assertNotIn('document.getElementById("ratesNote").innerHTML', source)


if __name__ == '__main__':
    unittest.main()
