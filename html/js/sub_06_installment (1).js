$(function () {


  const timelineSwiper = new Swiper(".timeline_wrap", {
    slidesPerView: 1.05,
    spaceBetween: 20,
    pagination: {
      el: ".swiper-pagination",
      clickable: true,
    },
    breakpoints: {
      769: {
        slidesPerView: 3,      // PC 항목 배치 수
        spaceBetween: 20,
        allowTouchMove: false,  // 드래그 비활성화
      },
    },
  });


  const swiper = new Swiper(".installment_wrap", {
    slidesPerView: 1.2,
    spaceBetween: 20,
    pagination: {
      el: ".swiper-pagination",
      clickable: true,
    },
    breakpoints: {
      769: { // PC에서는 스와이퍼 비활성화
        slidesPerView: 3,
        spaceBetween: 20,
        allowTouchMove: false, // 드래그 불가
      },
    },
  });



  gsap.registerPlugin(ScrollTrigger);

  gsap.to(".review_wrap", {
    scrollTrigger: {
      trigger: "#sec-review",
      start: "top 80%",   // 화면 80%쯤에 들어올 때 시작
      toggleActions: "play none none none"
    },
    opacity: 1,
    y: 0,
    duration: 1.2,
    ease: "power2.out"
  });

  // 각 후기 카드도 순차적으로 등장
  gsap.utils.toArray(".review_item").forEach((item, i) => {
    gsap.from(item, {
      scrollTrigger: {
        trigger: item,
        start: "top 85%",
      },
      opacity: 0,
      y: 30,
      duration: 0.8,
      delay: i * 0.1,
      ease: "power2.out"
    });
  });


  /* faq ============================================ */
  const faqItems = document.querySelectorAll(".faq_item");

  faqItems.forEach(item => {
    const question = item.querySelector(".faq_question");
    const answer = item.querySelector(".faq_answer");

    question.addEventListener("click", () => {
      const isOpen = item.classList.contains("active");

      // 다른 FAQ 닫기
      faqItems.forEach(i => {
        i.classList.remove("active");
        i.querySelector(".faq_answer").style.height = 0;
      });

      // 선택한 FAQ 열기
      if (!isOpen) {
        item.classList.add("active");
        answer.style.height = answer.scrollHeight + "px";
      } else {
        item.classList.remove("active");
        answer.style.height = 0;
      }
    });
  });




})