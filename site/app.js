// FreeRead 主页交互：深浅色、滚动揭示、导览、功能演示、外观试用、截图墙。
// 无框架、无构建。prefers-reduced-motion 时演示直接显示终态，不自动轮播。

(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const root = document.documentElement;

  /* ---------------------------------------------------------------- 深浅色 */

  const sysDark = matchMedia("(prefers-color-scheme: dark)");
  const isDark = () => (root.dataset.theme ? root.dataset.theme === "dark" : sysDark.matches);

  $(".theme-btn").addEventListener("click", () => {
    const next = isDark() ? "light" : "dark";
    root.dataset.theme = next;
    try {
      localStorage.setItem("freeread-site-theme", next);
    } catch {}
    syncDemoMode();
  });
  sysDark.addEventListener("change", () => syncDemoMode());

  /* ---------------------------------------------------------------- 分段控件底块 */

  function placeThumb(seg) {
    const thumb = $(".seg-thumb", seg);
    const on = $('button[aria-pressed="true"], button[aria-selected="true"]', seg);
    if (!thumb || !on) return;
    seg.style.setProperty("--seg-x", `${on.offsetLeft}px`);
    seg.style.setProperty("--seg-w", `${on.offsetWidth}px`);
    seg.dataset.ready = "";
  }

  function pick(seg, btn, attr = "aria-pressed") {
    for (const b of $$("button", seg)) b.setAttribute(attr, String(b === btn));
    placeThumb(seg);
  }

  const allSegs = () => $$(".seg").filter((s) => $(".seg-thumb", s));
  addEventListener("resize", () => allSegs().forEach(placeThumb));
  document.fonts?.ready.then(() => allSegs().forEach(placeThumb));

  /* ---------------------------------------------------------------- 顶栏 */

  const top = $(".top");
  const onScroll = () => top.classList.toggle("stuck", scrollY > 8);
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  const nav = $(".top-nav");
  const ind = $(".nav-ind");
  const links = $$("a", nav);
  const sections = links.map((a) => $(a.getAttribute("href")));
  const navIO = new IntersectionObserver(
    () => {
      // 取视口上部 40% 处所在的段落
      const y = innerHeight * 0.4;
      let idx = -1;
      sections.forEach((s, i) => {
        const r = s.getBoundingClientRect();
        if (r.top <= y && r.bottom > y) idx = i;
      });
      links.forEach((a, i) => a.classList.toggle("on", i === idx));
      if (idx < 0) {
        delete nav.dataset.active;
        return;
      }
      const a = links[idx];
      nav.dataset.active = "";
      ind.style.setProperty("--x", `${a.offsetLeft + a.offsetWidth / 2 - 8}px`);
    },
    { threshold: [0, 0.1, 0.25, 0.5, 0.75, 1], rootMargin: "-30% 0px -50% 0px" },
  );
  sections.forEach((s) => navIO.observe(s));

  /* ---------------------------------------------------------------- 滚动揭示 */

  const revealIO = new IntersectionObserver(
    (entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        e.target.classList.add("in");
        revealIO.unobserve(e.target);
      }
    },
    { rootMargin: "0px 0px -8% 0px" },
  );
  $$(".rv").forEach((el) => revealIO.observe(el));

  /* ---------------------------------------------------------------- 可见性 + 可取消的等待 */

  function visibility(el) {
    const state = { visible: false, waiters: [] };
    new IntersectionObserver(
      ([e]) => {
        state.visible = e.isIntersecting;
        if (state.visible) state.waiters.splice(0).forEach((f) => f());
      },
      { threshold: 0.25 },
    ).observe(el);
    state.when = () => (state.visible ? Promise.resolve() : new Promise((r) => state.waiters.push(r)));
    return state;
  }

  class Cancelled extends Error {}

  function runner(vis) {
    let token = { cancelled: false };
    return {
      cancel() {
        token.cancelled = true;
        token = { cancelled: false };
      },
      get token() {
        return token;
      },
      // 离开视口时暂停，回来后继续
      async sleep(ms, t) {
        const end = performance.now() + ms;
        while (performance.now() < end) {
          if (t.cancelled) throw new Cancelled();
          if (!vis.visible) await vis.when();
          await new Promise((r) => setTimeout(r, Math.min(60, end - performance.now())));
        }
        if (t.cancelled) throw new Cancelled();
      },
    };
  }

  /* ---------------------------------------------------------------- 导览 */

  const tour = $("[data-tour]");
  if (tour) {
    const win = $(".win", tour);
    const callouts = $$(".callout", tour);
    const vis = visibility(tour);
    const TOUR_MS = 4200;
    tour.style.setProperty("--tour-ms", `${TOUR_MS}ms`);
    let i = 0;
    let timer = 0;
    let auto = !reduced;
    if (!auto) tour.classList.remove("auto");

    const show = (idx) => {
      i = idx;
      callouts.forEach((c, j) => c.setAttribute("aria-pressed", String(j === idx)));
      const target = callouts[idx].dataset.target;
      $$("[data-zone]", win).forEach((z) => z.classList.toggle("zone-on", z.dataset.zone === target));
      win.classList.add("zoning");
      // 重新触发进度细线动画
      const c = callouts[idx];
      c.style.animation = "none";
      void c.offsetWidth;
      c.style.animation = "";
    };

    const tick = async () => {
      clearTimeout(timer);
      if (!auto) return;
      if (!vis.visible) await vis.when();
      timer = setTimeout(() => {
        if (!auto) return;
        show((i + 1) % callouts.length);
        tick();
      }, TOUR_MS);
    };

    callouts.forEach((c, j) =>
      c.addEventListener("click", () => {
        auto = false;
        tour.classList.remove("auto");
        clearTimeout(timer);
        show(j);
      }),
    );
    show(0);
    vis.when().then(tick);

    // 重排段落点一下，左边原版对应块亮起（双向定位示意）
    bindLocate(win);
  }

  function bindLocate(win) {
    for (const rf of $$(".w-reflow .rf[data-k]", win)) {
      rf.addEventListener("click", () => locate(win, rf.dataset.k));
    }
    for (const pb of $$(".pb[data-k]", win)) {
      pb.style.cursor = "pointer";
      pb.addEventListener("click", () => locate(win, pb.dataset.k));
    }
  }

  function locate(win, k) {
    $$(".rf", win).forEach((r) => r.classList.toggle("located", r.dataset.k === k));
    $$(".pb", win).forEach((p) => {
      const on = p.dataset.k === k;
      p.classList.toggle("on", on);
      p.classList.remove("pulse");
      if (on) {
        void p.offsetWidth;
        p.classList.add("pulse");
      }
    });
  }

  /* ---------------------------------------------------------------- 编号演示 */

  const steps = $("[data-steps]");
  if (steps) {
    const tabsSeg = $(".steps-tabs .seg", steps);
    const tabs = $$('[role="tab"]', steps);
    const panels = $$('[role="tabpanel"]', steps);
    const vis = visibility(steps);
    const run = runner(vis);
    let current = 0;
    let autoAdvance = !reduced;

    const demos = { reflow: demoReflow, translate: demoTranslate, qa: demoQa, engines: demoEngines };

    async function select(idx, user) {
      if (user) autoAdvance = false;
      current = idx;
      pick(tabsSeg, tabs[idx], "aria-selected");
      tabs.forEach((t, j) => (t.tabIndex = j === idx ? 0 : -1));
      panels.forEach((p, j) => {
        p.hidden = j !== idx;
        p.classList.remove("enter");
      });
      const panel = panels[idx];
      void panel.offsetWidth;
      panel.classList.add("enter");
      run.cancel();
      const t = run.token;
      try {
        await vis.when();
        await demos[panel.dataset.step](panel, t);
        if (!autoAdvance) return;
        await run.sleep(2600, t);
        if (autoAdvance && !t.cancelled) select((idx + 1) % tabs.length, false);
      } catch (e) {
        if (!(e instanceof Cancelled)) throw e;
      }
    }

    tabs.forEach((t, j) => t.addEventListener("click", () => select(j, true)));
    tabsSeg.addEventListener("keydown", (e) => {
      const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (!d) return;
      const n = (current + d + tabs.length) % tabs.length;
      tabs[n].focus();
      select(n, true);
    });
    // 用户在演示区里点来点去时，不再自动切到下一项
    $(".stage", steps).addEventListener("pointerdown", () => (autoAdvance = false));

    select(0, false);

    // 01 重排：重排块按阅读顺序浮现，原版对应块同时亮起
    async function demoReflow(panel, t) {
      const win = $(".win", panel);
      if (!win.dataset.bound) {
        bindLocate(win);
        win.dataset.bound = "1";
      }
      const blocks = $$(".rf", win);
      $$(".pb", win).forEach((p) => p.classList.remove("on", "pulse"));
      blocks.forEach((b) => b.classList.remove("located"));
      if (reduced) return;
      blocks.forEach((b) => b.classList.add("pending"));
      await run.sleep(400, t);
      for (const b of blocks) {
        locate(win, b.dataset.k);
        b.classList.remove("located");
        b.classList.remove("pending");
        await run.sleep(620, t);
      }
      $$(".pb", win).forEach((p) => p.classList.remove("on"));
      await run.sleep(500, t);
      // 演示反向：点重排第三段，原版定位
      locate(win, "3");
      await run.sleep(1400, t);
      locate(win, "6");
      await run.sleep(1400, t);
    }

    // 02 翻译：译文逐字流出，然后在四种显示方式之间切换
    async function demoTranslate(panel, t) {
      const modes = $("[data-tr-modes]", panel);
      const pairs = $$(".pair", panel);
      const trs = $$(".tr", panel);
      const setMode = (m) => {
        pairs.forEach((p) => (p.dataset.mode = m));
        pick(modes, $(`[data-mode="${m}"]`, modes));
      };
      if (!modes.dataset.bound) {
        modes.dataset.bound = "1";
        $$("button", modes).forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
      }
      setMode("side");
      placeThumb(modes);
      if (reduced) {
        trs.forEach((tr) => (tr.textContent = tr.dataset.text));
        return;
      }
      trs.forEach((tr) => (tr.textContent = ""));
      await run.sleep(500, t);
      for (const tr of trs) {
        await type(tr, tr.dataset.text, 34, t);
        await run.sleep(220, t);
      }
      for (const m of ["alternate", "only", "side"]) {
        await run.sleep(1500, t);
        setMode(m);
      }
      await run.sleep(600, t);
    }

    async function type(el, text, ms, t) {
      el.textContent = "";
      const caret = document.createElement("span");
      caret.className = "caret";
      el.append(caret);
      // 按 2–3 字一组流出，像流式返回
      for (let i = 0; i < text.length; ) {
        const n = 1 + Math.floor(Math.random() * 3);
        caret.before(text.slice(i, i + n));
        i += n;
        await run.sleep(ms * n, t);
      }
      caret.remove();
    }

    // 03 问答：衬线回答流出，引用编号指向左侧原文段落
    const ANSWER = [
      ["网络先同时处理序列和残基两两之间的关系，再把同一个结构送回去循环修正几轮", "b"],
      ["。每一轮都在局部坐标系里和实验结构比对，方向错了和位置错了都会被罚", "c"],
      ["，所以侧链和局部几何也能做得准确。", null],
    ];

    async function demoQa(panel, t) {
      const ans = $(".qa-a", panel);
      const src = $("[data-qa-src]", panel);
      const hl = (k) => $$(".rf", src).forEach((r) => r.classList.toggle("located", r.dataset.k === k));
      hl(null);
      ans.textContent = "";
      const cites = [];
      const addCite = (k, n) => {
        const b = document.createElement("button");
        b.className = "cite";
        b.type = "button";
        b.textContent = n;
        b.tabIndex = -1;
        b.addEventListener("mouseenter", () => hl(k));
        b.addEventListener("click", () => hl(k));
        ans.append(b);
        cites.push([b, k]);
      };
      let n = 1;
      for (const [text, k] of ANSWER) {
        if (reduced) ans.append(text);
        else {
          const span = document.createElement("span");
          ans.append(span);
          await type(span, text, 30, t);
        }
        if (k) addCite(k, n++);
      }
      if (reduced) return;
      for (const [b, k] of cites) {
        await run.sleep(900, t);
        cites.forEach(([c]) => c.classList.toggle("active", c === b));
        hl(k);
      }
      await run.sleep(1400, t);
      cites.forEach(([c]) => c.classList.remove("active"));
    }

    // 04 解析引擎：快速模式先完成，高质量引擎随后接手
    async function demoEngines(panel, t) {
      const rows = $$(".engine", panel);
      const bar = $("[data-jobs-bar]", panel);
      const label = $("[data-jobs-label]", panel);
      const count = $("[data-jobs-count]", panel);
      const setRow = (row, p, status, text) => {
        $(".progress i", row).style.setProperty("--p", `${p}%`);
        const tag = $(".tag", row);
        if (status) tag.dataset.status = status;
        else delete tag.dataset.status;
        tag.lastChild.textContent = text;
      };
      const plan = [
        ["快速解析", ["读取页面", "识别版面", "写入文献库"]],
        ["高质量解析 · MinerU", ["版面分析", "识别公式", "识别表格", "写入文献库"]],
        ["高质量解析 · Docling", ["上传文档", "等待服务", "写入文献库"]],
      ];
      rows.forEach((r) => setRow(r, 0, null, "排队中"));
      if (reduced) {
        rows.forEach((r) => setRow(r, 100, "ready", "可阅读"));
        bar.style.setProperty("--p", "100%");
        label.textContent = "全部完成";
        count.textContent = "";
        return;
      }
      await run.sleep(400, t);
      for (let i = 0; i < rows.length; i++) {
        const [name, phases] = plan[i];
        setRow(rows[i], 0, "parsing", "解析中");
        count.textContent = rows.length - i - 1 ? `1 个进行中，${rows.length - i - 1} 个排队` : "1 个进行中";
        const per = i === 0 ? 260 : 520;
        for (let s = 0; s < phases.length; s++) {
          label.textContent = `${name}：${phases[s]}`;
          const p = Math.round(((s + 1) / phases.length) * 100);
          setRow(rows[i], p, "parsing", "解析中");
          bar.style.setProperty("--p", `${p}%`);
          await run.sleep(per, t);
        }
        setRow(rows[i], 100, "ready", "可阅读");
        await run.sleep(300, t);
      }
      label.textContent = "全部完成";
      count.textContent = "";
      await run.sleep(800, t);
    }
  }

  /* ---------------------------------------------------------------- 外观试用 */

  // 与 apps/desktop/src/app/theme.ts 的 themeVars 相同的色阶与公式
  const LIGHT = {
    bg: "#FAF9F5", bg2: "#F0EEE6", surface: "#FFFFFF", ink: "#141413", ink2: "#3D3D3A", ink3: "#65645E",
    line: "#E6E3DA", line2: "#D4D0C4", hover: "rgba(20, 20, 19, 0.05)", ok: "#3F6B45", err: "#A3402F",
    btn: "#141413", "btn-ink": "#FAF9F5", page: "#FFFFFF",
  };
  const DARK = {
    bg: "#1F1E1D", bg2: "#262624", surface: "#30302E", ink: "#F3F1EA", ink2: "#D6D3C8", ink3: "#A6A398",
    line: "#3B3A37", line2: "#4C4A45", hover: "rgba(255, 255, 255, 0.06)", ok: "#9CC79C", err: "#EBA08C",
    btn: "#F3F1EA", "btn-ink": "#1F1E1D", page: "#ECEAE3",
  };
  const CONTRAST = {
    light: {
      medium: { ink2: "#2E2E2B", ink3: "#4F4E49", line: "#D4D0C4", line2: "#B9B4A6" },
      high: { ink2: "#1F1F1D", ink3: "#3D3D3A", line: "#B9B4A6", line2: "#8F8A7D" },
    },
    dark: {
      medium: { ink2: "#E4E1D7", ink3: "#C2BFB3", line: "#4C4A45", line2: "#625F58" },
      high: { ink2: "#F3F1EA", ink3: "#D6D3C8", line: "#625F58", line2: "#807C73" },
    },
  };
  const ACCENT_INK = {
    light: { standard: "70%", medium: "60%", high: "50%" },
    dark: { standard: "62%", medium: "50%", high: "40%" },
  };

  function themeVars(accent, dark, contrast) {
    const tone = dark ? "dark" : "light";
    const ramp = { ...(dark ? DARK : LIGHT), ...(contrast === "standard" ? {} : CONTRAST[tone][contrast]) };
    const vars = {};
    for (const [k, v] of Object.entries(ramp)) vars[`--${k}`] = v;
    vars["--accent"] = accent;
    vars["--accent-ink"] = `color-mix(in oklab, var(--accent) ${ACCENT_INK[tone][contrast]}, ${dark ? "#fff" : "#000"})`;
    vars["--accent-soft"] = `color-mix(in srgb, var(--accent) ${dark ? 22 : 14}%, transparent)`;
    return vars;
  }

  const custom = $("[data-custom]");
  const demo = { accent: "#D97757", mode: null, contrast: "standard" };
  let syncDemoMode = () => {};

  if (custom) {
    const win = $("[data-demo-win]", custom);
    const modeSeg = $('[data-opt="mode"]', custom);
    const conSeg = $('[data-opt="contrast"]', custom);
    const swatches = $$('[data-opt="accent"] .sw', custom);
    const swName = $("[data-sw-name]", custom);

    const apply = () => {
      const dark = (demo.mode ?? (isDark() ? "dark" : "light")) === "dark";
      for (const [k, v] of Object.entries(themeVars(demo.accent, dark, demo.contrast))) win.style.setProperty(k, v);
      win.style.colorScheme = dark ? "dark" : "light";
      pick(modeSeg, $(`[data-v="${dark ? "dark" : "light"}"]`, modeSeg));
    };
    // 没手动选过时，演示窗口跟随整页的深浅色
    syncDemoMode = apply;

    $$("button", modeSeg).forEach((b) =>
      b.addEventListener("click", () => {
        demo.mode = b.dataset.v;
        apply();
      }),
    );
    $$("button", conSeg).forEach((b) =>
      b.addEventListener("click", () => {
        demo.contrast = b.dataset.v;
        pick(conSeg, b);
        apply();
      }),
    );
    swatches.forEach((b) =>
      b.addEventListener("click", () => {
        demo.accent = b.dataset.v;
        swatches.forEach((s) => s.setAttribute("aria-pressed", String(s === b)));
        swName.textContent = `${b.dataset.name} · ${b.dataset.v}`;
        apply();
      }),
    );
    apply();
    placeThumb(conSeg);
  }

  /* ---------------------------------------------------------------- 截图墙 */

  const gallery = $("[data-gallery]");
  if (gallery) {
    const figs = $$("figure", gallery);
    $$("[data-gal]").forEach((b) =>
      b.addEventListener("click", () => {
        const w = figs[0].getBoundingClientRect().width + 20;
        gallery.scrollBy({ left: Number(b.dataset.gal) * w, behavior: reduced ? "auto" : "smooth" });
      }),
    );

    const box = $("[data-lightbox]");
    const boxImg = $("img", box);
    figs.forEach((f) =>
      $("button", f).addEventListener("click", () => {
        const shown = $$("img", f).find((im) => getComputedStyle(im).display !== "none");
        boxImg.src = shown.currentSrc || shown.src;
        boxImg.alt = shown.alt;
        box.showModal();
      }),
    );
    box.addEventListener("click", (e) => {
      if (e.target === box) box.close();
    });
  }

  /* ---------------------------------------------------------------- 最新版本 */

  // 页面里写的是发布时的版本，作为无脚本 / 请求失败时的兜底；
  // 打开时向 GitHub 查最新 Release，替换版本号和各安装包的文件名与链接。
  // 结果在本地缓存一小时，避免触发 API 的匿名限流（每 IP 每小时 60 次）。
  const RELEASE_API = "https://api.github.com/repos/cristimezzz/FreeRead/releases/latest";
  const RELEASE_KEY = "freeread-site-release";
  const RELEASE_TTL = 60 * 60 * 1000;
  // 与 apps/desktop/src-tauri/src/update.rs 选择安装包的规则一致
  const ASSET_SUFFIX = {
    setup: "_x64-setup.exe",
    portable: "_x64-portable.zip",
    appimage: "_amd64.AppImage",
    deb: "_amd64.deb",
    rpm: ".x86_64.rpm",
  };

  async function latestRelease() {
    try {
      const c = JSON.parse(localStorage.getItem(RELEASE_KEY));
      if (c && Date.now() - c.at < RELEASE_TTL) return c.release;
    } catch {}
    const r = await fetch(RELEASE_API, { headers: { Accept: "application/vnd.github+json" } });
    if (!r.ok) throw new Error(`GitHub ${r.status}`);
    const j = await r.json();
    const release = {
      version: j.tag_name.replace(/^v/, ""),
      assets: j.assets.map((a) => ({ name: a.name, url: a.browser_download_url })),
    };
    try {
      localStorage.setItem(RELEASE_KEY, JSON.stringify({ at: Date.now(), release }));
    } catch {}
    return release;
  }

  function applyRelease({ version, assets }) {
    if (!version) return;
    $$("[data-release-ver]").forEach((el) => (el.textContent = version));
    for (const el of $$("[data-asset]")) {
      const suffix = ASSET_SUFFIX[el.dataset.asset];
      const asset = suffix && assets.find((a) => a.name.endsWith(suffix));
      if (!asset) continue;
      if (el.tagName === "A") el.href = asset.url;
      else el.textContent = asset.name;
    }
  }

  latestRelease().then(applyRelease, () => {});

  allSegs().forEach(placeThumb);
})();
