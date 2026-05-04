$(function () {
    //scroll btn

    /* 1 */
    const button1 = document.getElementById('scroll-1');
    const shop = document.getElementById('sec-1');

    button1.addEventListener('click', () => {
        window.scrollBy({ top : shop.getBoundingClientRect().bottom - 80, behavior: 'smooth' });
    });

    /* 2 */
    const button2 = document.getElementById('scroll-2');
    const bulk = document.getElementById('sec-4');

    button2.addEventListener('click', () => {
        window.scrollBy({ top: bulk.getBoundingClientRect().top - 100, behavior: 'smooth' });
    });

    /* 3 */
    const button3 = document.getElementById('scroll-3');
    const topSection = document.getElementById('sec-1');

    button3.addEventListener('click', () => {
        window.scrollBy({ top: topSection.getBoundingClientRect().top, behavior: 'smooth' });
    });


    /* gsap */
    // use a script tag or an external JS file
    gsap.registerPlugin(ScrollTrigger)
    // gsap code here!

    gsap.fromTo("#sec-2",{ opacity: 0, y: 500 },{
        scrollTrigger: {
            trigger: "#sec-2",
            start: "-400 90%",
            end: "-400 90%",
            scrub: 3,
            markers: false,
        },
        y: 0,
        opacity: 1,
    });

    gsap.fromTo("#sec-3",{ opacity: 0, y: 500 },{
        scrollTrigger: {
            trigger: "#sec-3",
            start: "-400 90%",
            end: "-400 90%",
            scrub: 3,
            markers: false,
        },
        y: 0,
        opacity: 1,
    });
    
    gsap.fromTo("#sec-4 .left",{ opacity: 0, x: - 600 },{
        scrollTrigger: {
            trigger: "#sec-4 .left",
            start: "top 90%",
            end: "top 90%",
            scrub: 4,
            markers: false,
        },
        x: 0,
        opacity: 1,
    });

    gsap.fromTo("#sec-4 .right",{ opacity: 0, x: 600 },{
        scrollTrigger: {
            trigger: "#sec-4 .right",
            start: "top 90%",
            end: "top 90%",
            scrub: 4,
            markers: false,
        },
        x: 0,
        opacity: 1,
    });


});

$(window).on("load", function () {
  gsap.set(".right_img", {
    opacity: 0,
    y: 80
  });

  gsap.to(".right_img", {
    opacity: 1,
    y: 0,
    duration: 1.4,
    ease: "power3.out"
  });
});



