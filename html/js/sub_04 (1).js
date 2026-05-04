$(function () {

    /* 탭 */
    $('.category p').eq(0).addClass('on');

    $('.tab_body > ul').hide();
    $('.tab_body > ul').eq(0).show()

    $('.category p').click(function () {
        var i = $(this).index();

        $('.category p').removeClass('on');
        $(this).addClass('on');

        $('.tab_body > ul').hide();
        $('.tab_body > ul').eq(i).show()

        return false
    });


    /* faq */
    var i;
    var acc = document.getElementsByClassName("accordion");

    for (var i = 0; i < acc.length; i++) {
        acc[i].addEventListener("click", function () {
            var isActive = this.classList.contains("active");

            // 모든 패널 닫기
            for (var j = 0; j < acc.length; j++) {
                acc[j].classList.remove("active");
                acc[j].nextElementSibling.style.maxHeight = null;
            }

            // 현재 클릭한 항목이 열려 있지 않았다면 열기
            if (!isActive) {
                this.classList.add("active");
                var panel = this.nextElementSibling;
                panel.style.maxHeight = panel.scrollHeight + "px";
            }
        });
    }


});