// ===== Scroll-triggered reveal =====
const observer = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      }
    });
  },
  { threshold: 0.12, rootMargin: '0px 0px -40px 0px' }
);

document.querySelectorAll('.reveal').forEach((el) => observer.observe(el));

// ===== Nav scroll effect =====
const nav = document.querySelector('.nav');
window.addEventListener('scroll', () => {
  nav.classList.toggle('scrolled', window.scrollY > 20);
}, { passive: true });

// ===== CTA button text dance =====
document.querySelectorAll('.btn-primary .btn-text').forEach((el) => {
  const text = el.textContent;
  el.innerHTML = '';
  for (const char of text) {
    const span = document.createElement('span');
    span.textContent = char === ' ' ? '\u00a0' : char;
    el.appendChild(span);
  }
});

// ===== Marquee: duplicate content for seamless loop =====
const marqueeTrack = document.querySelector('.marquee-track');
if (marqueeTrack) {
  const items = marqueeTrack.innerHTML;
  marqueeTrack.innerHTML = items + items;
}

// ===== Video scroll-to-focus =====
const videoWrap = document.querySelector('.hero-video-wrap');
if (videoWrap) {
  const updateVideo = () => {
    const rect = videoWrap.getBoundingClientRect();
    const viewH = window.innerHeight;
    // progress ramps up as video scrolls into center of viewport
    const center = rect.top + rect.height / 2;
    const progress = Math.min(1, Math.max(0, 1 - (center - viewH * 0.5) / (viewH * 0.4)));
    const scale = 0.88 + progress * 0.12;
    const radius = 24 - progress * 8; // 24px → 16px
    const shadowAlpha = 0.18 + progress * 0.14;
    videoWrap.style.transform = `scale(${scale})`;
    videoWrap.style.borderRadius = `${radius}px`;
    videoWrap.style.boxShadow = `0 ${40 + progress * 20}px ${100 + progress * 40}px -20px rgba(0,0,0,${shadowAlpha}), 0 8px 32px rgba(0,0,0,${0.06 + progress * 0.06})`;
  };
  window.addEventListener('scroll', updateVideo, { passive: true });
  updateVideo();
}

// ===== Screenshot focus while scrolling =====
const showcaseDemos = Array.from(document.querySelectorAll('.showcase-demo'));
if (showcaseDemos.length) {
  let focusTicking = false;

  const updateShowcaseFocus = () => {
    const viewportCenter = window.innerHeight * 0.5;
    let activeDemo = null;
    let bestScore = -Infinity;

    showcaseDemos.forEach((demo) => {
      const rect = demo.getBoundingClientRect();
      const visible = Math.max(0, Math.min(rect.bottom, window.innerHeight) - Math.max(rect.top, 0));
      const visibleRatio = visible / Math.max(rect.height, 1);
      const demoCenter = rect.top + rect.height / 2;
      const centerDistance = Math.abs(demoCenter - viewportCenter);
      const score = visibleRatio * 1000 - centerDistance;

      if (visibleRatio > 0.18 && score > bestScore) {
        bestScore = score;
        activeDemo = demo;
      }
    });

    showcaseDemos.forEach((demo) => demo.classList.toggle('is-active', demo === activeDemo));
    focusTicking = false;
  };

  const requestShowcaseFocus = () => {
    if (!focusTicking) {
      focusTicking = true;
      requestAnimationFrame(updateShowcaseFocus);
    }
  };

  window.addEventListener('scroll', requestShowcaseFocus, { passive: true });
  window.addEventListener('resize', requestShowcaseFocus);
  updateShowcaseFocus();
}

// ===== Smooth scroll for anchor links =====
document.querySelectorAll('a[href^="#"]').forEach((a) => {
  a.addEventListener('click', (e) => {
    const target = document.querySelector(a.getAttribute('href'));
    if (target) {
      e.preventDefault();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
});
