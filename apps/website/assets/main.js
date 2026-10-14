// safearly.com: single page. No analytics, no third-party code.
// The live demo runs the real Saaf engine (copied to /assets/saaf/ by build.mjs).

document.documentElement.classList.remove("no-js");

// --- header shadow, mobile menu, active section ----------------------------
const top = document.querySelector(".top");
const onScroll = () => top?.classList.toggle("scrolled", window.scrollY > 8);
window.addEventListener("scroll", onScroll, { passive: true });
onScroll();

const menu = document.getElementById("menu");
const links = document.getElementById("links");
menu?.addEventListener("click", () => {
  const open = links.classList.toggle("open");
  menu.setAttribute("aria-expanded", String(open));
});
links?.addEventListener("click", (e) => {
  if (e.target.closest("a")) {
    links.classList.remove("open");
    menu?.setAttribute("aria-expanded", "false");
  }
});

const navLinks = [...document.querySelectorAll(".links a")];
if ("IntersectionObserver" in window) {
  // Reveal first: if anything below fails, the content must still show.
  const reveal = new IntersectionObserver(
    (entries) => {
      for (const en of entries) if (en.isIntersecting) { en.target.classList.add("in"); reveal.unobserve(en.target); }
    },
    { rootMargin: "0px 0px -8% 0px" },
  );
  document.querySelectorAll(".reveal").forEach((el) => reveal.observe(el));
  document.documentElement.classList.add("reveal-ready");

  // Highlight the in-page section links only (not /playground or external links).
  const sectionLinks = navLinks.filter((a) => /^#[\w-]+$/.test(a.getAttribute("href") ?? ""));
  const spy = new IntersectionObserver(
    (entries) => {
      for (const en of entries) {
        if (!en.isIntersecting) continue;
        for (const a of sectionLinks) a.classList.toggle("active", a.getAttribute("href") === `#${en.target.id}`);
      }
    },
    { rootMargin: "-45% 0px -50% 0px" },
  );
  sectionLinks.forEach((a) => {
    const target = document.getElementById(a.getAttribute("href").slice(1));
    if (target) spy.observe(target);
  });
}

// --- code tabs + copy ----------------------------------------------------
const tabs = [...document.querySelectorAll('[role="tab"]')];
function selectTab(tab) {
  for (const t of tabs) {
    const on = t === tab;
    t.setAttribute("aria-selected", String(on));
    t.tabIndex = on ? 0 : -1;
    document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
  }
}
tabs.forEach((t, i) => {
  t.addEventListener("click", () => selectTab(t));
  t.addEventListener("keydown", (e) => {
    const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!d) return;
    const next = tabs[(i + d + tabs.length) % tabs.length];
    selectTab(next);
    next.focus();
  });
});
document.querySelectorAll(".copy").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const code = btn.parentElement.querySelector("code")?.innerText ?? "";
    try {
      await navigator.clipboard.writeText(code);
      btn.textContent = "Copied";
    } catch {
      btn.textContent = "Select & copy";
    }
    setTimeout(() => (btn.textContent = "Copy"), 1600);
  });
});

// --- live demo -------------------------------------------------------------
const SAMPLES = {
  kyc:
    "Customer KYC\nName: Smt. Lakshmi Iyer\nAadhaar: 2345 6789 0124\nPAN: ABCPE1234F\n" +
    "GSTIN: 27ABCPE1234F1ZB\nMobile: +91 98765 43210\nUPI: lakshmi.iyer@okaxis",
  hinglish:
    "bhai mera adhaar २३४५ ६७८९ ०१२४ hai aur pan abcpe1234f\nphonepe pe bhej do 9876543210@ybl\nwhatsapp karo 987 654 3210",
  ocr: "AADHAAR: 2345 67B9 O124\nPAN card: ABCPE12B4F\nDOB: 14/08/1990",
  negatives:
    "Order ID 234567890124 shipped via AWB 987654321012.\nInvoice INV-2024-000123, txn id 9876543210, qty 12.",
};

const input = document.getElementById("demo-input");
if (input) {
  initDemo().catch(() => {
    document.getElementById("demo-masked").textContent = "The demo engine could not load. Please refresh the page.";
  });
}

async function initDemo() {
  const { Saaf } = await import("/assets/saaf/index.js");
  const reply = document.getElementById("demo-reply");
  const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  let saaf = new Saaf();

  function render() {
    saaf = new Saaf();
    const text = input.value;
    const r = saaf.mask(text);
    let html = "";
    let pos = 0;
    for (const { finding: f } of r.applied) {
      html += esc(text.slice(pos, f.start));
      html += `<mark title="score ${f.score.toFixed(2)}${f.ocrRepaired ? ", OCR-repaired" : ""}">${esc(text.slice(f.start, f.end))}<small>${f.entity}</small></mark>`;
      pos = f.end;
    }
    document.getElementById("demo-highlight").innerHTML = html + esc(text.slice(pos));
    document.getElementById("demo-chips").innerHTML = Object.keys(r.entityCounts).length
      ? Object.entries(r.entityCounts).map(([k, n]) => `<span class="chip">${esc(k)} × ${n}</span>`).join("")
      : '<span class="chip">Nothing to mask: look-alikes left alone</span>';
    document.getElementById("demo-masked").textContent = r.text;
    if (!reply.dataset.touched) {
      const toks = [...new Set(r.tokens)].slice(0, 3);
      reply.value = toks.length
        ? `I have verified ${toks.join(", ")}. ${toks[0].replace(/[[\]]/g, "").toLowerCase()}'s record looks fine.`
        : "Nothing was masked, so there is nothing to restore.";
    }
    restore();
  }
  const restore = () => (document.getElementById("demo-restored").textContent = saaf.restore(reply.value).text);

  document.querySelectorAll("[data-sample]").forEach((b) =>
    b.addEventListener("click", () => {
      document.querySelectorAll("[data-sample]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      input.value = SAMPLES[b.dataset.sample];
      delete reply.dataset.touched;
      render();
    }),
  );
  input.addEventListener("input", () => {
    delete reply.dataset.touched;
    render();
  });
  reply.addEventListener("input", () => {
    reply.dataset.touched = "1";
    restore();
  });
  input.value = SAMPLES.kyc;
  render();
}
