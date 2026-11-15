// 道の駅ポチ: 県ページの設備フィルタ。
// チェックした設備をすべて持つ駅だけを表示する（AND条件・ページ遷移なし）。
// JSが無効な環境ではこのファイル自体が動かず、全カードが見える状態が既定になる。
(function () {
  "use strict";
  var bar = document.querySelector(".ms-filter");
  if (!bar) return;
  var inputs = Array.prototype.slice.call(bar.querySelectorAll(".ms-filter-input"));
  var cards = Array.prototype.slice.call(document.querySelectorAll(".ms-cards .ms-card"));
  var countEl = bar.querySelector(".ms-filter-count");
  var emptyEl = bar.querySelector(".ms-filter-empty");
  var resetBtn = bar.querySelector(".ms-filter-reset");

  function apply() {
    var selected = inputs.filter(function (i) { return i.checked; })
                         .map(function (i) { return i.value; });
    var shown = 0;
    cards.forEach(function (card) {
      var feats = (card.getAttribute("data-feats") || "").split(/\s+/).filter(Boolean);
      var ok = selected.every(function (key) { return feats.indexOf(key) !== -1; });
      card.hidden = !ok;
      if (ok) shown += 1;
    });
    if (countEl) countEl.textContent = shown + "駅が該当";
    if (emptyEl) emptyEl.hidden = shown !== 0;
  }

  inputs.forEach(function (i) { i.addEventListener("change", apply); });
  if (resetBtn) {
    resetBtn.addEventListener("click", function () {
      inputs.forEach(function (i) { i.checked = false; });
      apply();
    });
  }
  apply();
})();
