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

// ===== Let the hero video pass quickly on the first downward gesture =====
const heroSection = document.querySelector('.hero');
const screenshotsSection = document.querySelector('#screenshots');
let heroSkipInProgress = false;

const shouldSkipHeroVideo = () => {
  if (!heroSection || !screenshotsSection || heroSkipInProgress) return false;

  const heroRect = heroSection.getBoundingClientRect();
  const screenshotsRect = screenshotsSection.getBoundingClientRect();
  const viewportH = window.innerHeight;

  return heroRect.top < 8 && heroRect.bottom > viewportH * 0.72 && screenshotsRect.top > viewportH * 0.55;
};

const skipHeroVideo = () => {
  if (!shouldSkipHeroVideo()) return false;

  heroSkipInProgress = true;
  screenshotsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  window.setTimeout(() => {
    heroSkipInProgress = false;
  }, 3000);

  return true;
};

window.addEventListener('wheel', (event) => {
  if (event.deltaY > 16 && shouldSkipHeroVideo()) {
    event.preventDefault();
    skipHeroVideo();
  }
}, { passive: false });

let heroTouchStartY = null;
window.addEventListener('touchstart', (event) => {
  heroTouchStartY = event.touches[0]?.clientY ?? null;
}, { passive: true });

window.addEventListener('touchmove', (event) => {
  if (heroTouchStartY === null) return;

  const currentY = event.touches[0]?.clientY ?? heroTouchStartY;
  if (heroTouchStartY - currentY > 18 && shouldSkipHeroVideo()) {
    event.preventDefault();
    heroTouchStartY = null;
    skipHeroVideo();
  }
}, { passive: false });

// ===== Screenshot focus while scrolling =====
const showcaseDemos = Array.from(document.querySelectorAll('.showcase-demo'));
if (showcaseDemos.length) {
  let focusTicking = false;
  let currentActiveDemo = null;
  const showcaseSection = showcaseDemos[0].closest('.screenshots');

  const setShowcasePlayback = (demo, shouldPlay) => {
    const img = demo.querySelector('img[data-gif-src]');
    if (!img) return;

    const gifSrc = img.dataset.gifSrc;
    const posterSrc = img.dataset.posterSrc;
    const isPlaying = img.dataset.playing === 'true';

    if (shouldPlay && !isPlaying) {
      img.src = `${gifSrc}?replay=${Date.now()}`;
      img.dataset.playing = 'true';
    } else if (!shouldPlay && isPlaying) {
      img.src = posterSrc;
      img.dataset.playing = 'false';
    }
  };

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

    if (activeDemo !== currentActiveDemo) {
      currentActiveDemo = activeDemo;
      showcaseDemos.forEach((demo) => setShowcasePlayback(demo, demo === activeDemo));
    }

    showcaseDemos.forEach((demo) => demo.classList.toggle('is-active', demo === activeDemo));
    if (showcaseSection) {
      showcaseSection.classList.toggle('is-focusing', Boolean(activeDemo));
    }
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

// ===== Screenshot lightbox =====
const lightboxButtons = Array.from(document.querySelectorAll('.showcase-image-button'));
if (lightboxButtons.length) {
  const lightbox = document.createElement('div');
  lightbox.className = 'image-lightbox';
  lightbox.setAttribute('aria-hidden', 'true');
  lightbox.innerHTML = `
    <div class="image-lightbox-inner" role="dialog" aria-modal="true" aria-label="图片预览">
      <button class="image-lightbox-close" type="button" aria-label="关闭图片预览">×</button>
      <img alt="">
      <div class="image-lightbox-title"></div>
    </div>
  `;
  document.body.appendChild(lightbox);

  const lightboxImg = lightbox.querySelector('img');
  const lightboxTitle = lightbox.querySelector('.image-lightbox-title');
  const lightboxClose = lightbox.querySelector('.image-lightbox-close');
  let lastFocusedElement = null;

  const closeLightbox = () => {
    lightbox.classList.remove('is-open');
    lightbox.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
    lightboxImg.removeAttribute('src');
    if (lastFocusedElement) {
      lastFocusedElement.focus();
      lastFocusedElement = null;
    }
  };

  const openLightbox = (button) => {
    lastFocusedElement = button;
    lightboxImg.src = button.dataset.lightboxSrc;
    lightboxImg.alt = button.querySelector('img')?.alt || button.dataset.lightboxTitle || '截图预览';
    lightboxTitle.textContent = button.dataset.lightboxTitle || '';
    lightbox.classList.add('is-open');
    lightbox.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    lightboxClose.focus();
  };

  lightboxButtons.forEach((button) => {
    button.addEventListener('click', () => openLightbox(button));
  });

  lightboxClose.addEventListener('click', closeLightbox);
  lightbox.addEventListener('click', (event) => {
    if (event.target === lightbox) closeLightbox();
  });

  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && lightbox.classList.contains('is-open')) {
      closeLightbox();
    }
  });
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
