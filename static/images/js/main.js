// static/js/main.js

document.addEventListener("DOMContentLoaded", function () {
  const track = document.getElementById("banner-carousel");
  const slides = track ? Array.from(track.children) : [];
  const total = slides.length;
  if (!track || total === 0) return;

  const prevBtn = document.getElementById("banner-prev");
  const nextBtn = document.getElementById("banner-next");
  const dots = Array.from(document.querySelectorAll(".banner-dot"));

  let current = 0;
  let paused = false;
  let timer = null;

  function update() {
    track.style.transform = `translateX(-${current * 100}%)`;
    dots.forEach((d, i) => {
      d.classList.toggle("bg-emerald-500", i === current);
      d.classList.toggle("bg-white/70", i !== current);
    });
  }

  function next() {
    current = (current + 1) % total;
    update();
  }

  function prev() {
    current = (current - 1 + total) % total;
    update();
  }

  // Button events
  if (nextBtn) nextBtn.addEventListener("click", () => { next(); resetAuto(); });
  if (prevBtn) prevBtn.addEventListener("click", () => { prev(); resetAuto(); });

  // Dot click
  dots.forEach((dot, index) => {
    dot.addEventListener("click", () => {
      current = index;
      update();
      resetAuto();
    });
  });

  // Pause on hover
  const section = track.parentElement;
  if (section) {
    section.addEventListener("mouseenter", () => { paused = true; });
    section.addEventListener("mouseleave", () => { paused = false; });
  }

  function startAuto() {
    timer = setInterval(() => {
      if (!paused) next();
    }, 4000);
  }

  function resetAuto() {
    if (timer) clearInterval(timer);
    startAuto();
  }

  // Initialize
  slides.forEach(slide => slide.classList.add("min-w-full"));
  update();
  startAuto();
});
