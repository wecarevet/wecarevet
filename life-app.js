/* 생활·세무 보드 (life.html)
   개인 데이터는 전부 localStorage 에만 저장됩니다. 소스에는 실제 개인정보를 넣지 않습니다.
   세법 기준: 2026년 11월 (소득세법 §55 · 조특법 §86의3 · 소득세법 §33의2) */
(function () {
  'use strict';

  var KEY = 'wecare.life.v2';
  var OLD = 'wecare.life.v1';   // 초기 버전 흔적 정리 (개인정보가 남지 않도록)

  /* ───────── 유틸 ───────── */
  function $(id) { return document.getElementById(id); }
  function num(v) { var n = parseFloat(String(v).replace(/,/g, '')); return isFinite(n) ? n : 0; }
  function nv(el) { return el ? num(el.value) : 0; }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function won(n) {
    n = Math.round(n || 0);
    var s = String(Math.abs(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return (n < 0 ? '-' : '') + '₩' + s;
  }
  function eok(n) {
    var a = Math.abs(n);
    if (a >= 100000000) return (n / 100000000).toFixed(a >= 1000000000 ? 0 : 1).replace(/\.0$/, '') + '억';
    if (a >= 10000) return Math.round(n / 10000) + '만';
    return String(Math.round(n));
  }
  function kst() { var d = new Date(Date.now() + 9 * 3600000); return { y: d.getUTCFullYear(), m: d.getUTCMonth() + 1, d: d.getUTCDate(), hh: d.getUTCHours(), mm: d.getUTCMinutes(), wd: d.getUTCDay() }; }
  function iso(y, m, d) { return y + '-' + pad(m) + '-' + pad(d); }
  function todayISO() { var t = kst(); return iso(t.y, t.m, t.d); }
  function ymd(s) { var p = String(s || '').split('-'); return { y: +p[0], m: +p[1], d: +p[2] }; }
  var WD = ['일', '월', '화', '수', '목', '금', '토'];
  function dateLabel(s) {
    if (!s) return '날짜 없음';
    var o = ymd(s); if (!o.y) return '날짜 없음';
    var dt = new Date(Date.UTC(o.y, o.m - 1, o.d));
    return o.m + '/' + o.d + '(' + WD[dt.getUTCDay()] + ')';
  }
  function dotDate(s) { if (!s) return '—'; var o = ymd(s); if (!o.y) return '—'; return o.y + '.' + pad(o.m) + '.' + pad(o.d); }
  function daysTo(s) {
    if (!s) return null;
    var o = ymd(s); if (!o.y) return null;
    var t = kst();
    return Math.round((Date.UTC(o.y, o.m - 1, o.d) - Date.UTC(t.y, t.m - 1, t.d)) / 86400000);
  }
  function plusMonths(s, months) {
    var o = ymd(s); if (!o.y) return '';
    var dt = new Date(Date.UTC(o.y, o.m - 1 + months, o.d));
    return iso(dt.getUTCFullYear(), dt.getUTCMonth() + 1, dt.getUTCDate());
  }
  function plusDays(s, days) {
    var o = ymd(s); if (!o.y) return '';
    var dt = new Date(Date.UTC(o.y, o.m - 1, o.d + days));
    return iso(dt.getUTCFullYear(), dt.getUTCMonth() + 1, dt.getUTCDate());
  }
  function ddText(n) { return n === null ? '' : (n > 0 ? 'D-' + n : (n === 0 ? 'D-DAY' : 'D+' + (-n))); }
  function create(tag, cls, html) { var e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
  var toastT;
  function toast(msg) {
    var t = $('toast'); t.textContent = msg; t.classList.add('on');
    clearTimeout(toastT); toastT = setTimeout(function () { t.classList.remove('on'); }, 1800);
  }

  /* ───────── 기본값 (개인정보 없음 · 모두 사용자 입력) ───────── */
  function DEF() {
    return {
      v: 2,
      clinic: {
        name: '', no: '', type: '', tax: '면세', faithful: false,
        rev: 0, other: 0,
        exp: [
          { n: '인건비', a: 0 },
          { n: '임대료', a: 0 },
          { n: '재료·약품비', a: 0 },
          { n: '세금과공과·보험', a: 0 },
          { n: '기타', a: 0 }
        ],
        dep: 0, npension: 0, interim: 0,
        yu: 0, pen: 0, irp: 0,
        carCost: 0, carPct: 0, carLog: false, carBooked: 0,
        hireWage: 0, hireN: 0,
        don: 0
      },
      car: {
        name: '', year: '', fuel: 'gas', insDue: '', premium: null,
        policy: '', vin: '', cover: '', memo: '',
        odo: null, maint: {}, ledger: []
      },
      dday: [
        { id: 'd1', t: '자동차보험 만기', d: '', c: '차', m: '만기일을 넣으면 비교 시작일(30일 전)도 자동 표시', done: false },
        { id: 'd2', t: '여권 만료일', d: '', c: '행정', m: '여권 사진면 만료일', done: false },
        { id: 'd3', t: '운전면허 갱신·적성검사', d: '', c: '행정', m: '면허증의 갱신기간 확인', done: false },
        { id: 'd4', t: '국가건강검진', d: '', c: '건강', m: '출생연도 기준 대상 연도 확인', done: false },
        { id: 'd5', t: '정기 구독 갱신 점검', d: '', c: '구독', m: '안 쓰는 구독 정리', done: false }
      ],
      subs: [],
      fx: 1380
    };
  }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }

  var S = clone(DEF());
  try {
    localStorage.removeItem(OLD);
    var raw = localStorage.getItem(KEY);
    if (raw) {
      var p = JSON.parse(raw);
      if (p && typeof p === 'object') S = merge(clone(DEF()), p);
    }
  } catch (e) { }
  function merge(base, over) {
    for (var k in over) {
      if (!Object.prototype.hasOwnProperty.call(over, k)) continue;
      var v = over[k];
      if (v && typeof v === 'object' && !Array.isArray(v) && base[k] && typeof base[k] === 'object' && !Array.isArray(base[k])) {
        merge(base[k], v);
      } else { base[k] = v; }
    }
    return base;
  }
  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(S)); } catch (e) { toast('저장 실패 — 저장 공간 확인'); }
  }
  function uid() { return 'x' + Date.now().toString(36) + Math.random().toString(36).slice(2, 5); }

  /* ───────── 세금 계산 ───────── */
  var BR = [
    [14000000, 0.06, 0],
    [50000000, 0.15, 1260000],
    [88000000, 0.24, 5760000],
    [150000000, 0.35, 15440000],
    [300000000, 0.38, 19940000],
    [500000000, 0.40, 25940000],
    [1000000000, 0.42, 35940000],
    [Infinity, 0.45, 65940000]
  ];
  function bracketOf(t) { for (var i = 0; i < BR.length; i++) if (t <= BR[i][0]) return BR[i]; return BR[BR.length - 1]; }
  function bracketTax(t) { if (t <= 0) return 0; var b = bracketOf(t); return t * b[1] - b[2]; }
  function bracketName(t) { var b = bracketOf(t); return (b[1] * 100).toFixed(0) + '%'; }

  /* 노란우산 소득공제 한도 — 사업소득금액 기준 (2025년 납입분부터) */
  function yuLimit(biz) {
    if (biz <= 40000000) return 6000000;
    if (biz <= 60000000) return 5000000;
    if (biz <= 100000000) return 4000000;
    return 2000000;
  }
  function expSum() { var s = 0; for (var i = 0; i < S.clinic.exp.length; i++) s += num(S.clinic.exp[i].a); return s; }
  function hireCost() { return num(S.clinic.hireWage) * 12 * 1.106 * num(S.clinic.hireN); }
  function carRecognized() {
    var c = num(S.clinic.carCost), cap = 15000000;
    if (S.clinic.carLog) return c * Math.max(0, Math.min(100, num(S.clinic.carPct))) / 100;
    return Math.min(c, cap);
  }
  function calc(zeros) {
    zeros = zeros || {};
    var t = S.clinic;
    var yu = zeros.yu ? 0 : num(t.yu);
    var pen = zeros.pen ? 0 : num(t.pen);
    var irp = zeros.irp ? 0 : num(t.irp);
    var car = zeros.car ? 0 : carRecognized() - num(t.carBooked);
    var hire = zeros.hire ? 0 : hireCost();
    var don = zeros.don ? 0 : num(t.don);

    var expTotal = expSum() + car + hire;
    var biz = num(t.rev) - expTotal;
    var total = biz + num(t.other);
    var yuCap = yuLimit(biz);
    var yuUse = Math.min(yu, yuCap);
    var donUse = Math.min(don, Math.max(0, biz) * 0.3);
    var baseDed = 1500000 * (1 + num(t.dep));
    var penDed = num(t.npension);
    var ded = baseDed + penDed + yuUse + donUse;
    var taxable = Math.max(0, total - ded);
    var gross = bracketTax(taxable);
    var penBase = Math.min(pen, 6000000) + Math.min(irp, 3000000);
    var rate = total <= 45000000 ? 0.165 : 0.132;
    var penCredit = penBase * rate;
    var stdCredit = t.faithful ? 120000 : 70000;
    var credit = Math.min(gross, penCredit + stdCredit);
    var det = Math.max(0, gross - credit);
    var local = Math.round(det * 0.1);
    return {
      expTotal: expTotal, biz: biz, total: total, yuCap: yuCap, yuUse: yuUse, donUse: donUse,
      baseDed: baseDed, penDed: penDed, ded: ded, taxable: taxable, gross: gross,
      penBase: penBase, rate: rate, penCredit: penCredit, stdCredit: stdCredit,
      credit: credit, det: det, local: local, all: det + local, carRec: car
    };
  }

  /* ───────── 탭 ───────── */
  var TABS = ['tax', 'car', 'life'];
  function showTab(name) {
    if (TABS.indexOf(name) < 0) name = 'tax';
    for (var i = 0; i < TABS.length; i++) $('pane-' + TABS[i]).classList.toggle('on', TABS[i] === name);
    var btns = document.querySelectorAll('.tab');
    for (var j = 0; j < btns.length; j++) btns[j].classList.toggle('on', btns[j].getAttribute('data-tab') === name);
    try { history.replaceState(null, '', '#' + name); } catch (e) { }
    if (name === 'car') { renderCar(); renderMaint(); renderLedger(); }
    if (name === 'life') { renderDday(); renderSubs(); }
  }

  /* ───────── 세무 탭 ───────── */
  function buildExp() {
    var box = $('expRows'); box.innerHTML = '';
    for (var i = 0; i < S.clinic.exp.length; i++) {
      (function (i) {
        var row = create('div', 'erow');
        var nm = create('input'); nm.type = 'text'; nm.value = S.clinic.exp[i].n; nm.setAttribute('aria-label', '경비 항목 이름');
        var am = create('input'); am.type = 'number'; am.step = '100000'; am.inputMode = 'numeric'; am.placeholder = '0'; am.setAttribute('aria-label', '경비 금액');
        if (num(S.clinic.exp[i].a)) am.value = S.clinic.exp[i].a;
        var del = create('button', 'del', '×'); del.type = 'button'; del.title = '삭제';
        nm.addEventListener('input', function () { S.clinic.exp[i].n = nm.value; save(); });
        am.addEventListener('input', function () { S.clinic.exp[i].a = nv(am); save(); $('expTotal').textContent = won(expSum()); renderTaxResults(); });
        del.addEventListener('click', function () { S.clinic.exp.splice(i, 1); save(); buildExp(); renderTaxResults(); });
        row.appendChild(nm); row.appendChild(am); row.appendChild(del);
        box.appendChild(row);
      })(i);
    }
    $('expTotal').textContent = won(expSum());
  }

  function buildLevers() {
    $('levers').innerHTML =
      levShell('yu', '🟡 노란우산공제', '소득공제 · 사업소득금액 따라 한도',
        '<label class="field"><span class="lb">연 납입액 <i>(원)</i></span><input type="number" id="yu" step="100000" inputmode="numeric" placeholder="0"></label>',
        '<div class="hintline" id="yuHint">—</div>') +
      levShell('pen', '📈 연금저축 + IRP', '세액공제 13.2~16.5% · 900만 한도',
        '<div class="grid2"><label class="field"><span class="lb">연금저축 <i>(600만 한도)</i></span><input type="number" id="pen" step="100000" inputmode="numeric" placeholder="0"></label>' +
        '<label class="field"><span class="lb">IRP <i>(300만 한도)</i></span><input type="number" id="irp" step="100000" inputmode="numeric" placeholder="0"></label></div>',
        '<div class="hintline" id="penHint">—</div>') +
      levShell('car', '🚗 업무용 승용차 경비', '운행기록부 · 인정 한도',
        '<div class="grid2"><label class="field"><span class="lb">연 관련비용 <i>(리스·보험·유류·정비·자동차세)</i></span><input type="number" id="carCost" step="10000" inputmode="numeric" placeholder="0"></label>' +
        '<label class="field"><span class="lb">업무 사용 비율 <i>(%)</i></span><input type="number" id="carPct" step="5" min="0" max="100" inputmode="numeric" placeholder="0"></label></div>' +
        '<div class="grid2" style="margin-top:6px"><label class="field"><span class="lb">장부에 이미 넣은 차량비 <i>(원)</i></span><input type="number" id="carBooked" step="10000" inputmode="numeric" placeholder="0"></label>' +
        '<div class="field"><span class="lb">운행기록부</span><label class="sw" style="padding-top:7px"><input type="checkbox" id="carLog"><span class="tr"></span>작성 중</label></div></div>',
        '<div class="hintline" id="carHint">—</div>') +
      levShell('hire', '👥 직원 인건비', '경비 · 4대보험 사업주 부담 10.6% 포함',
        '<div class="grid2"><label class="field"><span class="lb">월 급여 <i>(원)</i></span><input type="number" id="hireWage" step="100000" inputmode="numeric" placeholder="0"></label>' +
        '<label class="field"><span class="lb">인원 <i>(명)</i></span><input type="number" id="hireN" step="1" min="0" max="20" inputmode="numeric" placeholder="0"></label></div>',
        '<div class="hintline" id="hireHint">—</div>') +
      levShell('don', '🎁 기부금', '지정기부금 · 소득금액 30% 한도',
        '<label class="field"><span class="lb">연 기부액 <i>(원)</i></span><input type="number" id="don" step="100000" inputmode="numeric" placeholder="0"></label>',
        '<div class="hintline" id="donHint">—</div>');

    bind('yu'); bind('pen'); bind('irp'); bind('carCost'); bind('carPct'); bind('carBooked'); bind('hireWage'); bind('hireN'); bind('don');
    $('carLog').checked = !!S.clinic.carLog;
    $('carLog').addEventListener('change', function () { S.clinic.carLog = $('carLog').checked; save(); renderTaxResults(); });
  }
  function levShell(k, name, sub, fields, hint) {
    return '<div class="lever" id="lev-' + k + '">' +
      '<div class="lever-h"><div class="nm">' + name + '<i>' + sub + '</i></div>' +
      '<div class="sv" id="sv-' + k + '">—</div></div>' + fields + hint + '</div>';
  }
  function bind(id) {
    var el = $(id); if (!el) return;
    if (num(S.clinic[id])) el.value = S.clinic[id];
    el.addEventListener('input', function () { S.clinic[id] = nv(el); save(); renderTaxResults(); });
  }

  function renderTaxResults() {
    var c = calc();
    $('rBiz').textContent = won(c.biz);
    $('rTaxable').textContent = won(c.taxable);
    $('rGross').textContent = won(c.gross);
    $('rBracket').textContent = c.taxable > 0 ? bracketName(c.taxable) : '—';
    $('rDed').textContent = won(c.ded);
    $('rDedNote').textContent = '기본 ' + eok(c.baseDed) + ' · 연금 ' + eok(c.penDed) + ' · 노란우산 ' + eok(c.yuUse);
    $('rCredit').textContent = won(c.credit);
    $('rDet').textContent = won(c.det);
    $('rLocal').textContent = won(c.local);
    $('rAll').textContent = won(c.all);
    $('rEff').textContent = '매출 대비 ' + (num(S.clinic.rev) > 0 ? (c.all / num(S.clinic.rev) * 100).toFixed(1) : '0') + '%';
    var rest = c.all - Math.round(c.det * 0.5);
    $('rRest').textContent = (S.clinic.faithful ? '6/30' : '5/31') + ' 납부 ≈ ' + won(rest);
    $('faithBadge').textContent = S.clinic.faithful ? '성실신고' : '일반신고';
    $('faithBadge').className = 'badge' + (S.clinic.faithful ? '' : ' ghost');

    var steps = [
      ['매출 (공급가액)', won(num(S.clinic.rev))],
      ['− 필요경비 (입력 ' + won(expSum()) + ' + 차량 ' + won(c.carRec) + ' + 인건비 ' + won(hireCost()) + ')', won(c.expTotal)],
      ['= 사업소득금액', won(c.biz)],
      ['+ 매출 외 소득', won(num(S.clinic.other))],
      ['= 종합소득금액', won(c.total)],
      ['− 기본공제 (본인+부양 ' + num(S.clinic.dep) + '명)', won(c.baseDed)],
      ['− 국민연금 납부액', won(c.penDed)],
      ['− 노란우산 소득공제 (한도 ' + eok(c.yuCap) + ')', won(c.yuUse)],
      ['− 기부금 (30% 한도)', won(c.donUse)],
      ['= 과세표준', won(c.taxable)],
      ['× 세율 − 누진공제 (' + bracketName(c.taxable) + ')', won(c.gross)],
      ['− 연금저축·IRP 세액공제 (' + (c.rate * 100).toFixed(1) + '%)', won(c.penCredit)],
      ['− 표준세액공제', won(c.stdCredit)],
      ['= 결정세액 (국세)', won(c.det)],
      ['+ 지방소득세 10%', won(c.local)],
      ['= 총 부담', won(c.all)]
    ];
    var h = '';
    for (var i = 0; i < steps.length; i++) h += '<div class="ln"><em>' + steps[i][0] + '</em><b>' + steps[i][1] + '</b></div>';
    $('calcSteps').innerHTML = h;

    /* 레버 */
    var base = calc({ yu: 1, pen: 1, irp: 1, car: 1, hire: 1, don: 1 });
    var defs = ['yu', 'pen', 'irp', 'car', 'hire', 'don'];
    var cur = c.all, m = {};
    for (var j = 0; j < defs.length; j++) {
      var z = {}; z[defs[j]] = 1;
      m[defs[j]] = calc(z).all - cur;
    }
    setSave('yu', m.yu);
    setSave('pen', m.pen + m.irp);
    setSave('car', m.car);
    setSave('hire', m.hire);
    setSave('don', m.don);
    var totalSave = base.all - cur;
    $('savingTotal').textContent = totalSave > 0 ? '− ' + won(totalSave) : won(totalSave);
    $('savingTotal').style.color = totalSave > 0 ? 'var(--up)' : (totalSave < 0 ? 'var(--warn)' : 'var(--txt)');

    $('lev-yu').classList.toggle('on', num(S.clinic.yu) > 0);
    $('lev-pen').classList.toggle('on', num(S.clinic.pen) + num(S.clinic.irp) > 0);
    $('lev-car').classList.toggle('on', carRecognized() - num(S.clinic.carBooked) > 0);
    $('lev-hire').classList.toggle('on', num(S.clinic.hireN) > 0);
    $('lev-don').classList.toggle('on', num(S.clinic.don) > 0);

    $('yuHint').innerHTML = '사업소득금액 ' + eok(c.biz) + ' 기준 한도 <b>' + eok(yuLimit(c.biz)) + '</b> · 반영 ' + won(c.yuUse) +
      (num(S.clinic.yu) > yuLimit(c.biz) ? ' (한도 초과 ' + won(num(S.clinic.yu) - yuLimit(c.biz)) + '은 공제 없음)' : '');
    $('penHint').innerHTML = '공제 대상 ' + won(c.penBase) + ' × ' + (c.rate * 100).toFixed(1) + '% = <b>' + won(c.penCredit) + '</b>' +
      (c.total <= 45000000 ? ' · 종합소득금액 4,500만 이하 → 16.5%' : ' · 4,500만 초과 → 13.2%');
    $('carHint').innerHTML = '인정액 <b>' + won(carRecognized()) + '</b> / 관련비용 ' + won(num(S.clinic.carCost)) +
      (S.clinic.carLog ? ' · 운행기록부 기준 ' + Math.round(Math.min(100, num(S.clinic.carPct))) + '%' : ' · 운행기록부 없음 → 연 1,500만 한도') +
      ' · 감가상각 상당액은 연 800만 별도 한도';
    $('hireHint').innerHTML = '연 지출 <b>' + won(hireCost()) + '</b> (급여 ' + won(num(S.clinic.hireWage) * 12 * num(S.clinic.hireN)) + ' + 사업주 4대보험 10.6%)';
    $('donHint').innerHTML = '한도 ' + won(Math.max(0, c.biz) * 0.3) + ' (사업소득금액의 30%) · 반영 ' + won(c.donUse);

    /* 적립 통장 */
    var mSave = Math.round(c.all / 12 / 10000) * 10000;
    $('monthSave').textContent = won(mSave);
    $('monthSaveSub').textContent = c.all > 0 ? '연 세금의 1/12 · 매출 대비 ' + (c.all / Math.max(1, num(S.clinic.rev)) * 100).toFixed(1) + '%' : '손익을 넣으면 계산됩니다';
    $('midTax').textContent = won(c.det * 0.5);
    $('restTax').textContent = won(rest);
    $('saveRate').textContent = (num(S.clinic.rev) > 0 ? (c.all / num(S.clinic.rev) * 100).toFixed(1) : '0') + '%';
    var paid = num(S.clinic.interim);
    var pct = c.all > 0 ? Math.min(100, paid / c.all * 100) : 0;
    $('reserveBar').style.width = pct.toFixed(1) + '%';
    $('reserveNote').textContent = paid > 0
      ? '이미 낸 ' + won(paid) + ' = 필요액의 ' + pct.toFixed(0) + '%. 남은 ' + won(Math.max(0, c.all - paid)) + '을 ' + (S.clinic.faithful ? '6/30' : '5/31') + '까지 준비하면 됩니다.'
      : '11/30 중간예납 ' + won(c.det * 0.5) + ', ' + (S.clinic.faithful ? '6/30' : '5/31') + ' 잔액 ' + won(rest) + ' 구조입니다.';
  }
  function setSave(k, v) {
    var el = $('sv-' + k); if (!el) return;
    if (Math.abs(v) < 1) { el.textContent = '—'; el.className = 'sv'; }
    else if (v > 0) { el.textContent = '− ' + won(v); el.className = 'sv down'; }
    else { el.textContent = '+ ' + won(-v); el.className = 'sv up'; }
  }

  function renderCalendar() {
    var t = kst();
    var ev = [], years = [t.y, t.y + 1];
    for (var i = 0; i < years.length; i++) {
      var y = years[i];
      ev.push({ d: iso(y, 2, 10), t: '면세사업자 사업장현황신고', s: (y - 1) + '년 귀속 · 원천세도 같은 날', tag: '신고' });
      ev.push({ d: iso(y, 3, 10), t: '근로소득 지급명세서 제출', s: (y - 1) + '년분 · 직원 있으면', tag: '신고' });
      ev.push({ d: iso(y, 5, 31), t: '종합소득세 신고·납부', s: (y - 1) + '년 귀속 · 일반신고', tag: '국세' });
      ev.push({ d: iso(y, 6, 16), t: '자동차세 1기분', s: '연납 아님 기준', tag: '지방세' });
      ev.push({ d: iso(y, 6, 30), t: '성실신고확인 종합소득세', s: (y - 1) + '년 귀속 · 확인서 첨부', tag: '국세' });
      ev.push({ d: iso(y, 7, 10), t: '원천세 + 상반기 지급명세서', s: '6월분', tag: '원천세' });
      ev.push({ d: iso(y, 7, 16), t: '재산세 (주택)', s: '7월분', tag: '지방세' });
      ev.push({ d: iso(y, 9, 16), t: '재산세 (토지·건축물)', s: '9월분', tag: '지방세' });
      ev.push({ d: iso(y, 11, 30), t: '종합소득세 중간예납', s: '결정세액의 50%', tag: '국세' });
      ev.push({ d: iso(y, 12, 16), t: '자동차세 2기분', s: '연납 아님 기준', tag: '지방세' });
    }
    ev.sort(function (a, b) { return a.d < b.d ? -1 : 1; });
    var h = '<div class="ci"><div class="d">매월</div><div class="t">원천세 신고·납부 (10일)<i>상시근로자 있으면 매월 · 소규모는 반기납부(1/10·7/10)</i></div><div class="dd">상시</div></div>';
    var shown = 0;
    for (var k = 0; k < ev.length && shown < 12; k++) {
      var n = daysTo(ev[k].d);
      if (n === null || n < 0) continue;
      h += '<div class="ci' + (n <= 14 ? ' near' : '') + '"><div class="d">' + dateLabel(ev[k].d) + '</div>' +
        '<div class="t">' + ev[k].t + '<i>' + ev[k].s + '</i></div>' +
        '<div class="dd">' + ddText(n) + '</div></div>';
      shown++;
    }
    $('calendar').innerHTML = h;
  }

  /* ───────── 차 탭 ───────── */
  var FUEL = { gas: '가솔린', diesel: '디젤', hev: '하이브리드(HEV)', phev: '플러그인 하이브리드', ev: '전기', lpg: 'LPG' };

  function maintItems() {
    var f = S.car.fuel, it = [];
    var elect = (f === 'hev' || f === 'phev' || f === 'ev');
    if (f !== 'ev') {
      it.push({ k: 'oil', n: '엔진오일 + 오일필터', sp: '12개월 / 10,000km', km: 10000, mo: 12, note: elect ? '엔진 가동이 적은 차는 주행거리보다 기간(12개월)이 먼저 옵니다' : '' });
      it.push({ k: 'air', n: '에어클리너 (엔진)', sp: '24개월 / 30,000km', km: 30000, mo: 24 });
    }
    if (f === 'diesel') {
      it.push({ k: 'fuel', n: '연료필터 (디젤)', sp: '24개월 / 30,000km', km: 30000, mo: 24 });
      it.push({ k: 'urea', n: '요소수 · DPF 점검', sp: '12개월', km: null, mo: 12, note: '장거리 위주면 요소수 소모가 빠릅니다' });
    }
    if (f === 'lpg') it.push({ k: 'fuel', n: '연료필터 (LPG)', sp: '24개월 / 30,000km', km: 30000, mo: 24 });
    it.push({ k: 'cabin', n: '에어컨 필터', sp: '12개월 / 15,000km', km: 15000, mo: 12 });
    it.push({ k: 'brake', n: '브레이크액', sp: '24개월', km: null, mo: 24, note: '흡습성이라 기간 기준' });
    if (f === 'ev') it.push({ k: 'reduc', n: '감속기 오일', sp: '24개월 / 40,000km', km: 40000, mo: 24 });
    if (elect) it.push({ k: 'hv', n: '고전압 배터리·충전 점검', sp: '12개월', km: null, mo: 12, note: 'SOH·냉각 호스·리콜 확인' });
    it.push({ k: 'cool', n: '냉각수', sp: '48개월 / 60,000km', km: 60000, mo: 48, note: elect ? '배터리 냉각 회로 포함' : '' });
    it.push({ k: 'tire', n: '타이어 위치교환', sp: '6개월 / 8,000km', km: 8000, mo: 6 });
    it.push({ k: 'wear', n: '타이어 마모·공기압', sp: '3개월', km: null, mo: 3 });
    it.push({ k: 'wiper', n: '와이퍼 블레이드', sp: '12개월', km: null, mo: 12 });
    it.push({ k: 'pad', n: '브레이크 패드 점검', sp: '12개월', km: null, mo: 12, note: elect ? '회생제동으로 마모는 적지만 점검은 필요' : '' });
    it.push({ k: 'bat', n: '12V 보조배터리 점검', sp: '12개월', km: null, mo: 12 });
    return it;
  }
  function maintState(it) {
    var rec = S.car.maint[it.k] || {};
    var odo = S.car.odo != null ? num(S.car.odo) : null;
    var out = { rec: rec, kmLeft: null, dayLeft: null, dueKm: null, dueDate: '' };
    if (rec.km != null && rec.km !== '') {
      out.dueKm = num(rec.km) + (it.km || 0);
      if (it.km && odo) out.kmLeft = out.dueKm - odo;
    }
    if (it.mo && rec.d) { out.dueDate = plusMonths(rec.d, it.mo); out.dayLeft = daysTo(out.dueDate); }
    return out;
  }
  function renderCar() {
    var c = S.car;
    $('carTitle').textContent = c.name || '내 차';
    $('carFuelShow').textContent = FUEL[c.fuel] || '—';
    $('carYearShow').textContent = c.year || '연식 미입력';
    $('carDue').textContent = c.insDue ? dotDate(c.insDue) : '미입력';
    var n1 = daysTo(c.insDue);
    $('carDueSub').textContent = c.insDue ? ddText(n1) + (n1 < 0 ? ' 지남' : '') : '만기일을 넣어주세요';
    var cmp = c.insDue ? plusDays(c.insDue, -30) : '';
    $('carCmp').textContent = cmp ? dateLabel(cmp) : '—';
    var n2 = daysTo(cmp);
    $('carCmpSub').textContent = cmp ? (n2 > 0 ? n2 + '일 뒤 시작' : (n2 === 0 ? '오늘부터 조회 가능' : '조회 가능')) : '만기 30일 전';
    $('carPremium').textContent = num(c.premium) ? won(c.premium) : '—';
    var badge = $('carInsBadge');
    if (!c.insDue) { badge.textContent = '만기 미입력'; badge.className = 'badge ghost'; }
    else { badge.textContent = ddText(n1); badge.className = 'badge' + (n1 <= 45 ? '' : ' ghost'); }
  }
  function renderMaint() {
    var box = $('maintList'); box.innerHTML = '';
    var odoEl = $('odo');
    if (S.car.odo != null) odoEl.value = S.car.odo;
    var items = maintItems(), hot = 0, soon = 0;
    for (var i = 0; i < items.length; i++) {
      (function (it) {
        var st = maintState(it);
        var row = create('div', 'mt-row');
        var pills = '', lvl = '';
        if (st.kmLeft !== null) {
          var kc = st.kmLeft <= 0 ? 'hot' : (st.kmLeft <= 1000 ? 'soon' : 'ok');
          if (kc === 'hot') lvl = 'hot'; else if (kc === 'soon' && lvl !== 'hot') lvl = 'soon';
          pills += '<span class="pill ' + kc + '">' + (st.kmLeft <= 0 ? '주행 ' + Math.abs(Math.round(st.kmLeft)).toLocaleString('ko-KR') + 'km 초과' : '앞으로 ' + Math.round(st.kmLeft).toLocaleString('ko-KR') + 'km') + '</span>';
        }
        if (st.dayLeft !== null) {
          var dc = st.dayLeft <= 0 ? 'hot' : (st.dayLeft <= 30 ? 'soon' : 'ok');
          if (dc === 'hot') lvl = 'hot'; else if (dc === 'soon' && lvl !== 'hot') lvl = 'soon';
          pills += '<span class="pill ' + dc + '">' + (st.dayLeft <= 0 ? Math.abs(st.dayLeft) + '일 지남' : st.dayLeft + '일 남음') + ' · ' + dateLabel(st.dueDate) + '</span>';
        }
        if (!S.car.odo && it.km && st.rec.km != null && st.rec.km !== '') pills = '<span class="pill none">주행거리 입력 필요</span>' + pills;
        if (!pills) pills = '<span class="pill none">마지막 기록을 넣으면 계산됩니다</span>';
        if (lvl === 'hot') hot++; else if (lvl === 'soon') soon++;

        row.innerHTML =
          '<div class="mt-top"><div class="nm">' + it.n + '</div><div class="sp">' + it.sp + '</div></div>' +
          (it.note ? '<div class="hintline">' + it.note + '</div>' : '') +
          '<div class="mt-next">' + pills + '</div>' +
          '<div class="mt-in">' +
          '<label class="field"><span class="lb">마지막 km</span><input type="number" step="100" inputmode="numeric" data-k="km" value="' + (st.rec.km != null ? st.rec.km : '') + '" placeholder="예: 19000"></label>' +
          '<label class="field"><span class="lb">마지막 날짜</span><input type="date" data-k="d" value="' + (st.rec.d || '') + '"></label>' +
          '<button class="btn sm" type="button">다음 시기 계산</button>' +
          '</div>';
        var commit = function () {
          var kmI = row.querySelector('input[data-k="km"]'), dI = row.querySelector('input[data-k="d"]');
          S.car.maint[it.k] = { km: kmI.value === '' ? null : num(kmI.value), d: dI.value || '' };
          save(); renderMaint(); renderLedger(); toast(it.n + ' 저장');
        };
        var ins = row.querySelectorAll('input');
        for (var j = 0; j < ins.length; j++) ins[j].addEventListener('change', commit);
        row.querySelector('button').addEventListener('click', commit);
        box.appendChild(row);
      })(items[i]);
    }
    var sm = $('maintSummary');
    if (hot) { sm.textContent = hot + '건 시기 지남'; sm.className = 'pill hot'; }
    else if (soon) { sm.textContent = soon + '건 임박'; sm.className = 'pill soon'; }
    else { sm.textContent = '임박 없음'; sm.className = 'pill ok'; }
  }

  var TYPE_EMOJI = { '주유': '⛽', '충전': '🔌', '정비': '🔧', '세차': '🧼', '보험': '🛡', '기타': '•' };
  function ledgerSorted() {
    return S.car.ledger.slice().sort(function (a, b) {
      if (a.d !== b.d) return a.d < b.d ? 1 : -1;
      return (b.id || '') < (a.id || '') ? -1 : 1;
    });
  }
  function addLedger() {
    var amt = nv($('lgAmt'));
    if (!amt) { toast('금액을 넣어주세요'); return; }
    S.car.ledger.push({
      id: uid(), d: $('lgDate').value || todayISO(), t: $('lgType').value, amt: amt,
      km: $('lgKm').value === '' ? null : nv($('lgKm')),
      qty: $('lgQty').value === '' ? null : nv($('lgQty')),
      memo: $('lgMemo').value.trim()
    });
    if ($('lgKm').value !== '') S.car.odo = nv($('lgKm'));
    $('lgAmt').value = ''; $('lgQty').value = ''; $('lgMemo').value = '';
    save(); renderLedger(); renderMaint();
    toast('기록 추가');
  }
  function renderLedger() {
    var rows = ledgerSorted(), t = kst();
    var thisM = 0, yearT = 0, thisKey = t.y + '-' + pad(t.m), months = {};
    var maxKm = null, minKm = null, fuelL = 0, evKwh = 0;
    for (var i = 0; i < rows.length; i++) {
      var e = rows[i], mk = String(e.d || '').slice(0, 7);
      yearT += num(e.amt);
      months[mk] = (months[mk] || 0) + num(e.amt);
      if (mk === thisKey) thisM += num(e.amt);
      if (e.km != null && e.km !== '') {
        var k = num(e.km);
        if (maxKm === null || k > maxKm) maxKm = k;
        if (minKm === null || k < minKm) minKm = k;
      }
      if (e.t === '주유' && e.qty) fuelL += num(e.qty);
      if (e.t === '충전' && e.qty) evKwh += num(e.qty);
    }
    $('lgTotalM').textContent = won(thisM);
    $('lgTotalY').textContent = won(yearT);
    $('lgAvg').textContent = won(yearT / Math.max(1, Object.keys(months).length));
    var trip = (maxKm !== null && minKm !== null) ? maxKm - minKm : null;
    $('lgEff').textContent = (trip && fuelL) ? (trip / fuelL).toFixed(1) + ' km/L' : '—';
    $('lgEffEv').textContent = (trip && evKwh) ? (trip / evKwh).toFixed(2) + ' km/kWh' : '기록 쌓이면 계산';

    var mh = '', keys = Object.keys(months).sort();
    if (!keys.length) mh = '<div class="empty">아직 기록이 없습니다. 주유·충전 한 번부터 넣어보세요.</div>';
    else {
      var mx = 0;
      for (var a = 0; a < keys.length; a++) if (months[keys[a]] > mx) mx = months[keys[a]];
      for (var b = keys.length - 1; b >= 0 && b >= keys.length - 6; b--) {
        var k2 = keys[b];
        mh += '<div class="lm"><span class="m">' + k2.slice(5) + '월</span>' +
          '<span class="track"><i style="width:' + (mx > 0 ? months[k2] / mx * 100 : 0).toFixed(1) + '%"></i></span>' +
          '<span class="a num">' + won(months[k2]) + '</span></div>';
      }
    }
    $('lgMonth').innerHTML = mh;

    var lh = '';
    if (!rows.length) lh = '<div class="empty">기록 없음</div>';
    for (var c = 0; c < rows.length && c < 12; c++) {
      var r = rows[c];
      lh += '<div class="lgent">' +
        '<span class="dt">' + String(r.d || '').slice(5).replace('-', '/') + '</span>' +
        '<span class="ty">' + (TYPE_EMOJI[r.t] || '•') + ' ' + r.t + '</span>' +
        '<span class="km">' + (r.km != null ? r.km.toLocaleString('ko-KR') + 'km' : '') +
        (r.qty ? (r.km != null ? ' · ' : '') + r.qty + (r.t === '충전' ? 'kWh' : 'L') : '') + '</span>' +
        '<span class="memo">' + (r.memo || '') + '</span>' +
        '<span class="am num">' + won(r.amt) + '</span>' +
        '<button class="iconbtn del" type="button" data-id="' + r.id + '">삭제</button>' +
        '</div>';
    }
    $('lgList').innerHTML = lh;
    var dels = $('lgList').querySelectorAll('.iconbtn.del');
    for (var e2 = 0; e2 < dels.length; e2++) {
      dels[e2].addEventListener('click', function () {
        var id = this.getAttribute('data-id');
        S.car.ledger = S.car.ledger.filter(function (x) { return x.id !== id; });
        save(); renderLedger(); toast('삭제');
      });
    }
  }

  /* ───────── D-day 탭 ───────── */
  var CAT_EMOJI = { '행정': '🗂', '세무': '💰', '차': '🚗', '구독': '💳', '건강': '🩺', '사업': '🏥' };
  function ddaySorted() {
    return S.dday.slice().sort(function (a, b) {
      if (a.done !== b.done) return a.done ? 1 : -1;
      if (!a.d && !b.d) return 0;
      if (!a.d) return 1;
      if (!b.d) return -1;
      return a.d < b.d ? -1 : 1;
    });
  }
  function renderDday() {
    var box = $('ddayList'); box.innerHTML = '';
    var list = ddaySorted(), open = 0;
    for (var i = 0; i < list.length; i++) {
      (function (it) {
        var n = it.d ? daysTo(it.d) : null, cls = 'dd';
        if (it.done) cls += ' done';
        else if (n !== null && n <= 7) cls += ' hot';
        else if (n !== null && n <= 30) cls += ' soon';
        if (!it.done && n !== null && n >= 0) open++;
        var el = create('div', cls);
        el.innerHTML =
          '<div><div class="tt"><span class="tag">' + (CAT_EMOJI[it.c] || '•') + ' ' + (it.c || '기타') + '</span>' + it.t + '</div>' +
          (it.m ? '<div class="mt">' + it.m + '</div>' : '') +
          '<div class="acts">' +
          '<input type="date" data-k="d" value="' + (it.d || '') + '" style="width:130px;padding:4px 6px;font-size:11.5px;border-radius:8px">' +
          '<button class="iconbtn" data-act="done" type="button">' + (it.done ? '되돌리기' : '완료') + '</button>' +
          '<button class="iconbtn del" data-act="del" type="button">삭제</button>' +
          '</div></div>' +
          '<div class="right"><div class="v num">' + (it.d ? ddText(n) : '<span style="font-size:13px;color:var(--mut2)">날짜</span>') + '</div>' +
          '<small>' + (it.d ? dateLabel(it.d) : '입력 전') + '</small></div>';
        el.querySelector('input[data-k="d"]').addEventListener('change', function () {
          it.d = this.value || ''; save(); renderDday(); renderAlerts(); renderCalendar();
        });
        el.querySelector('[data-act="done"]').addEventListener('click', function () { it.done = !it.done; save(); renderDday(); renderAlerts(); });
        el.querySelector('[data-act="del"]').addEventListener('click', function () {
          S.dday = S.dday.filter(function (x) { return x.id !== it.id; });
          save(); renderDday(); renderAlerts(); toast('삭제');
        });
        box.appendChild(el);
      })(list[i]);
    }
    if (!list.length) box.innerHTML = '<div class="empty">항목이 없습니다. 아래에서 추가하세요.</div>';
    $('ddLeftBadge').textContent = open + '건 남음';
  }
  function addDday() {
    var t = $('ddTitle').value.trim();
    if (!t) { toast('항목 이름을 넣어주세요'); return; }
    S.dday.push({ id: uid(), t: t, d: $('ddDate').value || '', c: $('ddCat').value, m: $('ddMemo').value.trim(), done: false });
    $('ddTitle').value = ''; $('ddDate').value = ''; $('ddMemo').value = '';
    save(); renderDday(); renderAlerts(); toast('추가');
  }

  function subMonthly(v) { var fx = v.cur === 'USD' ? num(S.fx) : 1; return num(v.amt) * fx / (v.cycle === 'm' ? 1 : 12); }
  function renderSubs() {
    var box = $('subList'); box.innerHTML = '';
    var mSum = 0, ySum = 0, active = 0, next = null;
    var arr = S.subs.slice().sort(function (a, b) {
      if (a.off !== b.off) return a.off ? 1 : -1;
      if (!a.next || !b.next) return 0;
      return a.next < b.next ? -1 : 1;
    });
    for (var i = 0; i < arr.length; i++) {
      (function (v) {
        if (!v.off) {
          mSum += subMonthly(v); ySum += subMonthly(v) * 12; active++;
          if (v.next && (!next || v.next < next.next)) next = v;
        }
        var el = create('div', 'dd');
        if (v.off) el.className = 'dd done';
        var n = v.next ? daysTo(v.next) : null;
        var cur = v.cur === 'USD' ? '$' + num(v.amt) : won(v.amt);
        el.innerHTML =
          '<div><div class="tt">' + v.n + '</div>' +
          '<div class="mt">' + cur + ' / ' + (v.cycle === 'm' ? '월' : '년') +
          (v.cur === 'USD' ? ' · ' + won(num(v.amt) * num(S.fx)) : '') + ' · ' + (v.card || '결제수단 미입력') + '</div>' +
          '<div class="acts">' +
          '<input type="date" data-k="d" value="' + (v.next || '') + '" style="width:130px;padding:4px 6px;font-size:11.5px;border-radius:8px">' +
          '<button class="iconbtn" data-act="off" type="button">' + (v.off ? '사용 중으로' : '해지 표시') + '</button>' +
          '<button class="iconbtn del" data-act="del" type="button">삭제</button>' +
          '</div></div>' +
          '<div class="right"><div class="v num" style="font-size:15px">' + (v.off ? '해지' : won(subMonthly(v))) + '</div>' +
          '<small>' + (v.off ? '결제 없음' : (n !== null ? ddText(n) : '날짜 전')) + '</small></div>';
        el.querySelector('input[data-k="d"]').addEventListener('change', function () { v.next = this.value || ''; save(); renderSubs(); renderAlerts(); });
        el.querySelector('[data-act="off"]').addEventListener('click', function () { v.off = !v.off; save(); renderSubs(); renderAlerts(); });
        el.querySelector('[data-act="del"]').addEventListener('click', function () {
          S.subs = S.subs.filter(function (x) { return x.id !== v.id; });
          save(); renderSubs(); renderAlerts(); toast('삭제');
        });
        box.appendChild(el);
      })(arr[i]);
    }
    if (!arr.length) box.innerHTML = '<div class="empty">아직 구독을 넣지 않았습니다.<br>아래에서 추가하면 월·연 합계가 자동 집계됩니다.</div>';
    $('subMonthly').textContent = won(mSum);
    $('subAnnual').textContent = won(ySum);
    $('subCount').textContent = '사용 중 ' + active + '개';
    $('subNext').textContent = next ? (next.next || '').slice(5).replace('-', '/') : '—';
    $('subNextSub').textContent = next ? next.n + ' · ' + ddText(daysTo(next.next)) : '—';
    $('fxShow').textContent = num(S.fx).toLocaleString('ko-KR');
    if ($('fx') && document.activeElement !== $('fx')) $('fx').value = S.fx;
  }
  function addSub() {
    var n = $('sbName').value.trim(), amt = nv($('sbAmt'));
    if (!n || !amt) { toast('서비스와 금액을 넣어주세요'); return; }
    S.subs.push({
      id: uid(), n: n, amt: amt, cur: $('sbCur').value, cycle: $('sbCycle').value,
      next: $('sbNext').value || '', card: $('sbCard').value.trim(), off: false
    });
    $('sbName').value = ''; $('sbAmt').value = ''; $('sbNext').value = '';
    save(); renderSubs(); renderAlerts(); toast('구독 추가');
  }

  /* ───────── 상단 알림 ───────── */
  function renderAlerts() {
    var items = [];
    for (var i = 0; i < S.dday.length; i++) {
      var it = S.dday[i];
      if (it.done || !it.d) continue;
      var n = daysTo(it.d);
      if (n === null || n > 40) continue;
      items.push({ t: it.t, n: n });
    }
    items.sort(function (a, b) { return a.n - b.n; });
    var h = '';
    for (var j = 0; j < items.length && j < 4; j++) {
      var cls = items[j].n <= 7 ? 'hot' : (items[j].n <= 30 ? 'soon' : 'ok');
      h += '<span class="al ' + cls + '"><b>' + ddText(items[j].n) + '</b> ' + items[j].t + '</span>';
    }
    $('alerts').innerHTML = h || '<span class="al ok">임박한 일정 없음 · D-day 보드에 날짜를 넣어보세요</span>';
  }

  /* ───────── 내보내기 / 불러오기 ───────── */
  function exportJSON() {
    var out = { app: 'life-board', v: 2, exportedAt: new Date().toISOString(), data: S };
    var blob = new Blob([JSON.stringify(out, null, 2)], { type: 'application/json' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'life-board-' + todayISO() + '.json';
    document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1200);
    toast('JSON 파일로 내보냈습니다');
  }
  function importJSON(file) {
    var fr = new FileReader();
    fr.onload = function () {
      try {
        var p = JSON.parse(String(fr.result));
        var data = p && p.data ? p.data : p;
        if (!data || typeof data !== 'object') throw new Error('형식 오류');
        S = merge(clone(DEF()), data);
        save(); boot(); toast('불러왔습니다');
      } catch (e) { toast('불러오기 실패 — 파일 확인'); }
    };
    fr.readAsText(file);
  }

  /* ───────── 부팅 ───────── */
  function clock() {
    var t = kst();
    $('clock').textContent = pad(t.hh) + ':' + pad(t.mm);
    $('today').textContent = t.m + '월 ' + t.d + '일 (' + WD[t.wd] + ')';
  }
  function fillCarFields() {
    var c = S.car;
    $('carName').value = c.name || '';
    $('carYear').value = c.year || '';
    $('carFuel').value = c.fuel || 'gas';
    $('carInsDue').value = c.insDue || '';
    $('carPremiumIn').value = num(c.premium) ? c.premium : '';
    $('carPolicy').value = c.policy || '';
    $('carVin').value = c.vin || '';
    $('carCover').value = c.cover || '';
    $('carMemo').value = c.memo || '';
  }
  function boot() {
    clock();
    $('clName').value = S.clinic.name || '';
    $('clNo').value = S.clinic.no || '';
    $('clType').value = S.clinic.type || '';
    $('clTax').value = S.clinic.tax || '면세';
    $('rev').value = num(S.clinic.rev) || '';
    $('otherInc').value = num(S.clinic.other) || '';
    $('dependents').value = num(S.clinic.dep) || '';
    $('npension').value = num(S.clinic.npension) || '';
    $('interim').value = num(S.clinic.interim) || '';
    $('faithful').checked = !!S.clinic.faithful;
    $('lgDate').value = todayISO();
    buildExp();
    buildLevers();
    fillCarFields();
    renderTaxResults();
    renderCalendar();
    renderAlerts();
    renderCar();
    renderMaint();
    renderLedger();
    renderDday();
    renderSubs();
  }

  function wire() {
    var btns = document.querySelectorAll('.tab');
    for (var i = 0; i < btns.length; i++) btns[i].addEventListener('click', function () { showTab(this.getAttribute('data-tab')); });

    /* 사업장 */
    [['clName', 'name'], ['clNo', 'no'], ['clType', 'type']].forEach(function (p) {
      var el = $(p[0]);
      el.addEventListener('input', function () { S.clinic[p[1]] = el.value; save(); });
    });
    $('clTax').addEventListener('change', function () { S.clinic.tax = this.value; save(); });
    $('faithful').addEventListener('change', function () { S.clinic.faithful = this.checked; save(); renderTaxResults(); });

    /* 손익 */
    [['rev', 'rev'], ['otherInc', 'other'], ['dependents', 'dep'], ['npension', 'npension'], ['interim', 'interim']].forEach(function (p) {
      var el = $(p[0]);
      el.addEventListener('input', function () { S.clinic[p[1]] = nv(el); save(); renderTaxResults(); });
    });
    $('addExp').addEventListener('click', function () {
      S.clinic.exp.push({ n: '새 항목', a: 0 }); save(); buildExp(); renderTaxResults();
    });

    /* 차량 정보 */
    [['carName', 'name'], ['carYear', 'year'], ['carPolicy', 'policy'], ['carVin', 'vin'], ['carCover', 'cover'], ['carMemo', 'memo']].forEach(function (p) {
      var el = $(p[0]);
      el.addEventListener('input', function () { S.car[p[1]] = el.value; save(); if (p[1] === 'name') renderCar(); });
    });
    $('carFuel').addEventListener('change', function () { S.car.fuel = this.value; save(); renderCar(); renderMaint(); });
    $('carInsDue').addEventListener('change', function () { S.car.insDue = this.value || ''; save(); renderCar(); renderAlerts(); });
    $('carPremiumIn').addEventListener('input', function () { S.car.premium = this.value === '' ? null : nv(this); save(); renderCar(); });

    /* 주행·가계부 */
    $('odo').addEventListener('input', function () { S.car.odo = this.value === '' ? null : nv(this); save(); renderMaint(); });
    $('lgDate').value = todayISO();
    $('lgAdd').addEventListener('click', addLedger);

    /* D-day / 구독 */
    $('ddAdd').addEventListener('click', addDday);
    $('sbAdd').addEventListener('click', addSub);
    $('fx').addEventListener('input', function () { S.fx = nv(this) || 1380; save(); renderSubs(); });

    /* 도구 */
    $('expBtn').addEventListener('click', exportJSON);
    $('impBtn').addEventListener('click', function () { $('impFile').click(); });
    $('impFile').addEventListener('change', function () { if (this.files && this.files[0]) importJSON(this.files[0]); this.value = ''; });
    $('resetBtn').addEventListener('click', function () {
      if (!window.confirm('입력한 내용을 모두 지우고 처음 상태로 돌아갑니다. 계속할까요?')) return;
      try { localStorage.removeItem(KEY); } catch (e) { }
      S = clone(DEF()); boot(); toast('초기화');
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    wire();
    boot();
    var h = (location.hash || '').replace('#', '');
    if (TABS.indexOf(h) >= 0) showTab(h);
    setInterval(clock, 20000);
  });
})();
