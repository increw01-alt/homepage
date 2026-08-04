$(function () {
    $(window).scroll(function () {
        var st = $(this).scrollTop();
        var offset = '10';
        if (st >= offset) { //  위치보다 스크롤탑 값이 큰 경우
            $('#gnb').addClass('bg_white');
            $('.pc_navi_wrap').addClass('black');
            $('.mob_navi_wrap').addClass('black');


        } else { // 작거나 같은 경우
            $('#gnb').removeClass('bg_white');
            $('.pc_navi_wrap').removeClass('black');
            $('.mob_navi_wrap').removeClass('black');
        }
        /* console.log(st, offset) */
    });//end scroll
    $(window).trigger('resize');


    ///////////////////////////

    // 헤더는 항상 상단 고정 — 이전의 "아래로 스크롤하면 숨기기(scrollDown)" 동작은
    // 2026-08-04 제거함 (스크롤 시 메뉴바가 움직이지 않도록)


    // PC 메뉴를 기준으로 모바일 메뉴 생성
    const pcMenu = document.querySelector('.pc_navi_wrap .menu');
    const mobWrap = document.querySelector('.mob_menu_wrap');

    if (pcMenu && mobWrap) {
        // PC 메뉴 복제
        const clonedMenu = pcMenu.cloneNode(true);

        // 모바일 메뉴용 클래스로 변경
        clonedMenu.className = 'mob_menu';

        // li 구조도 모바일에 맞게 조정 (예: <div class="sub-wrap"> → 바로 <ul class="submenu">)
        clonedMenu.querySelectorAll('.sub-wrap').forEach(div => {
            const ul = div.querySelector('.submenu');
            div.replaceWith(ul); // div 제거하고 ul만 남김
        });

        mobWrap.appendChild(clonedMenu);
    }


    // mob navi
    // mob navi
    $('.menu-button').click(function () {
        $(this).toggleClass('cross');

        if ($(this).hasClass('cross')) {
            $('.mob_menu_wrap').addClass('on');
            $('.mob_navi_wrap').addClass('on');
            $('body').css({
                overflowY: 'hidden',
                position: 'fixed'
            });

        } else {
            $('.mob_menu_wrap').removeClass('on');
            $('.mob_navi_wrap').removeClass('on');
            $('body').css({
                overflowY: 'auto',
                position: 'static'
            });
        }
    });

    // 970px 이상에서는 body 스타일 초기화
    $(window).on('resize', function () {
        if ($(window).width() > 970) {
            $('body').css({
                overflowY: '',
                position: ''
            });

            // 모바일 메뉴 강제 초기화도 필요하다면 아래도 추가
            $('.menu-button').removeClass('cross');
            $('.mob_menu_wrap, .mob_navi_wrap').removeClass('on');
        }
    });

    /* ////// */



    /* 모바일 네비 메뉴 터치 */
    const menuItems = document.querySelectorAll('.mob_menu li.has-submenu > a');

    menuItems.forEach(item => {
        item.addEventListener('click', e => {
            e.preventDefault();

            const submenu = item.nextElementSibling; // 바로 뒤의 .sub-wrap

            if (submenu.classList.contains('open')) {
                // 닫기
                submenu.style.height = submenu.scrollHeight + "px"; // 현재 높이 고정
                requestAnimationFrame(() => {
                    submenu.style.height = "0";
                    submenu.style.opacity = "0";
                    submenu.style.marginTop = "0";
                });
                submenu.classList.remove('open');
                item.classList.remove('rotate'); // 자체에 rotate 제거
            } else {
                // 열기
                submenu.classList.add('open');
                submenu.style.opacity = "1";
                submenu.style.marginTop = "3rem";
                const height = submenu.scrollHeight; // 실제 높이
                submenu.style.height = height + "px";
                item.classList.add('rotate'); // 자체에 rotate 추가
            }
        });
    });




});