// 전역 함수: 팝업 닫기
window.hidePopup = function(popupEl, hours = 0, popupName = "default") {
  if(popupEl) popupEl.remove();

  if(hours > 0){
    const date = new Date();
    date.setTime(date.getTime() + hours*60*60*1000);
    document.cookie = `popup_hide_${popupName}=Y; expires=${date.toUTCString()}; path=/`;
  }
}

$(function() {
  function getCookie(name) {
    const cookies = document.cookie.split("; ");
    for (let c of cookies) {
      const [key, val] = c.split("=");
      if(key === name) return val;
    }
    return null;
  }

  // fetch로 popup.html 불러오기
  fetch("popup.html")
    .then(res => res.text())
    .then(html => {
      document.body.insertAdjacentHTML("beforeend", html);

      // 모든 팝업 처리
      document.querySelectorAll('.popup').forEach(popup => {
        const popupName = popup.dataset.popup || "default";

        // 쿠키 확인
        if(getCookie(`popup_hide_${popupName}`) === "Y") {
          popup.remove();
          return;
        }

        // X 버튼 (즉시 닫기)
        const closeX = popup.querySelector('.close-x');
        if(closeX) closeX.addEventListener('click', () => window.hidePopup(popup, 0, popupName));

        // n시간 안보기 버튼
        const closeN = popup.querySelector('.close-n');
        if(closeN){
          const hours = parseInt(closeN.dataset.hours) || 0;
          closeN.addEventListener('click', () => window.hidePopup(popup, hours, popupName));
        }
      });
    });
});
