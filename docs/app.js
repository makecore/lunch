(() => {
  const DOW = ["일", "월", "화", "수", "목", "금", "토"];
  // 밥·김치·샐러드처럼 매일 나오는 기본 반찬은 작게 보여 준다.
  const STAPLE = /^(쌀밥|흰밥|백미밥|잡곡밥|현미밥|흑미밥|보리밥|기장밥|귀리밥|.*김치|깍두기|섞박지|총각김치|그린샐러드|양상추샐러드|.*샐러드바|단무지|숭늉|누룽지|요구르트|요플레|야쿠르트|.*음료|.*주스|우유)$/;

  const pad = n => String(n).padStart(2, "0");
  const iso = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const kstToday = () => new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Seoul" }));
  const mondayOf = d => { const x = new Date(d); x.setHours(0,0,0,0); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); return x; };
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));

  const today = kstToday();
  const todayIso = iso(today);
  let selected = todayIso;
  let weekStart = mondayOf(today);
  let data = null;

  function hasMenu(dateIso) {
    return data && data.restaurants.some(r => {
      const d = r.days[dateIso];
      return d && d.meals.some(m => !m.closed && m.items.length);
    });
  }

  function renderWeek() {
    const box = document.getElementById("days");
    box.innerHTML = "";
    for (let i = 0; i < 7; i++) {
      const d = new Date(weekStart); d.setDate(d.getDate() + i);
      const key = iso(d);
      const b = document.createElement("button");
      b.type = "button";
      b.className = "ticket" + (key === todayIso ? " today" : "");
      b.setAttribute("aria-pressed", key === selected ? "true" : "false");
      b.setAttribute("aria-label", `${d.getMonth() + 1}월 ${d.getDate()}일 ${DOW[d.getDay()]}요일${key === todayIso ? ", 오늘" : ""}${hasMenu(key) ? "" : ", 식단 없음"}`);
      b.innerHTML = `<span class="dow">${key === todayIso ? "오늘" : DOW[d.getDay()]}</span><span class="num">${d.getDate()}</span>${hasMenu(key) ? '<span class="dot"></span>' : ""}`;
      b.addEventListener("click", () => { selected = key; render(); });
      box.appendChild(b);
    }
  }

  function renderMeal(m) {
    if (m.closed) {
      return `<div class="meal"><h3>${esc(m.label)}</h3><p class="closed">운영하지 않습니다</p></div>`;
    }
    if (!m.items.length) return `<div class="meal"><h3>${esc(m.label)}</h3><p class="closed">메뉴 정보가 없습니다</p></div>`;
    const mains = m.items.filter(i => !STAPLE.test(i.replace(/\s/g, "")));
    const sides = m.items.filter(i => STAPLE.test(i.replace(/\s/g, "")));
    const list = (mains.length ? mains : m.items).map(i => `<li>${esc(i)}</li>`).join("");
    return `<div class="meal"><h3>${esc(m.label)}</h3><ul class="mains">${list}</ul>${
      mains.length && sides.length ? `<p class="sides">${sides.map(esc).join(", ")}</p>` : ""}</div>`;
  }

  function imageFor(r, dateIso) {
    const day = r.days[dateIso];
    if (day && day.image) return r.images.find(i => i.path === day.image) || { path: day.image };
    return r.images.find(i => i.week_start && i.week_end && i.week_start <= dateIso && dateIso <= i.week_end);
  }

  function renderPlace(r) {
    const day = r.days[selected];
    const img = imageFor(r, selected);
    let body;
    if (day && day.meals.length) {
      const allClosed = day.meals.every(m => m.closed);
      body = allClosed
        ? `<p class="empty">운영하지 않습니다.</p>`
        : day.meals.filter(m => !(m.closed && m.label === "석식" && day.meals.length > 1 && r.id === "nl")).map(renderMeal).join("");
    } else if (img && img.pending) {
      // 식단표는 받았지만 글자로 옮기기 전
      body = `<p class="empty"><strong>식단표는 올라와 있습니다.</strong> 아래 <strong>원본 식단표</strong>에서 메뉴를 확인해 주세요.</p>`;
    } else if (r.problem) {
      // 식당은 식단을 올렸을 수도 있지만, 이 페이지가 가져오지 못한 경우
      body = `<p class="notice"><strong>식단 정보를 잠시 가져오지 못하고 있습니다.</strong> 식당 운영과는 관계없는 문제입니다.${
        r.source_url ? " 아래 <strong>식당 게시판</strong>에서 직접 확인해 주세요." : " 잠시 뒤 다시 확인해 주세요."}</p>`;
    } else if (r.method === "photo") {
      // 사진으로 받는 식당: 이 페이지에 식단 사진이 아직 등록되지 않은 경우
      body = `<p class="empty">식단 사진이 아직 등록되지 않았습니다.</p>`;
    } else {
      // 선택한 날짜의 정보가 없는 경우; 실제 게시 여부를 단정하지 않는다.
      body = `<p class="empty">선택한 날짜의 식단 정보가 없습니다.</p>`;
    }

    if (day && r.problem) body += '<p class="notice">최신 정보를 가져오지 못해 이전 수집 내용을 표시합니다. 원본을 확인해 주세요.</p>';
    const foot = [];
    if (day && day.source === "image" && day.verified) foot.push('<span class="badge ok">두 번 읽어 일치</span>');
    if (day && day.source === "image" && !day.verified) {
      foot.push(`<span class="badge check" title="식단표 사진에서 옮겨 적은 메뉴라 일부 글자가 다를 수 있습니다">원본과 대조해 주세요</span>`);
    }
    if (img) foot.push(`<a href="${esc(img.path)}" target="_blank" rel="noopener">원본 식단표</a>`);
    if (r.source_url) foot.push(`<a href="${esc(r.source_url)}" target="_blank" rel="noopener">식당 게시판</a>`);

    return `<section class="place" aria-labelledby="h-${esc(r.id)}">
      <h2 id="h-${esc(r.id)}">${esc(r.name)}</h2>
      <p class="where">${esc(r.place)}</p>${r.info ? `<p class="info">${esc(r.info)}</p>` : ""}
      ${body}
      <div class="foot">${foot.join("")}</div>
    </section>`;
  }

  function render() {
    const d = new Date(selected + "T00:00:00");
    document.getElementById("title").textContent =
      `${d.getMonth() + 1}월 ${d.getDate()}일 ${DOW[d.getDay()]}요일`;
    document.getElementById("subtitle").textContent =
      (selected === todayIso ? "오늘 · " : "") + "국립중앙도서관 · 서울지방조달청 · 아펠가모 반포";
    renderWeek();
    if (!data) return;
    document.getElementById("board").innerHTML = data.restaurants.map(renderPlace).join("");
  }

  document.getElementById("today").addEventListener("click", () => {
    selected = todayIso; weekStart = mondayOf(today); render();
  });
  function shiftWeek(n) {
    weekStart.setDate(weekStart.getDate() + 7 * n);
    const sameDow = new Date(weekStart);
    const cur = new Date(selected + "T00:00:00");
    sameDow.setDate(sameDow.getDate() + ((cur.getDay() + 6) % 7));
    selected = iso(sameDow);
    render();
  }
  document.getElementById("prev").addEventListener("click", () => shiftWeek(-1));
  document.getElementById("next").addEventListener("click", () => shiftWeek(1));

  function start(json) {
    if (!json || !Array.isArray(json.restaurants)) throw new Error("Invalid menu data");
    data = json;
    const u = new Date(new Date(data.updated).toLocaleString("en-US", { timeZone: "Asia/Seoul" }));
    document.getElementById("updated").textContent =
      `${u.getMonth() + 1}월 ${u.getDate()}일 ${pad(u.getHours())}:${pad(u.getMinutes())} 기준`;
    render();
  }

  render();
  fetch("data/menus.json", { cache: "no-store" })
    .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(start)
    .catch(() => {
      document.getElementById("board").innerHTML =
        `<p class="empty"><strong>식단 데이터를 불러오지 못했습니다.</strong> 잠시 뒤 다시 시도해 주세요.</p><button type="button" id="retry">다시 불러오기</button>`;
      document.getElementById("retry").addEventListener("click", () => location.reload());
    });
})();
