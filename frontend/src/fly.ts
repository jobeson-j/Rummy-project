// Card-flight animations (Web Animations API). Elements are animated FROM a
// source rectangle TO wherever the layout already placed them, so the game
// state stays the single source of truth and animations can never desync it.

// True if the user's system asks for reduced motion.
export const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const EASE = 'cubic-bezier(0.2, 0.75, 0.25, 1)';

// On-screen rectangle of the first element matching a selector.
export function rectOf(selector: string): DOMRect | null {
  return document.querySelector<HTMLElement>(selector)?.getBoundingClientRect() ?? null;
}

// Animates an element from a starting rectangle to where it now sits.
export function flyFrom(
  el: HTMLElement,
  from: DOMRect,
  { delay = 0, duration = 460, rotate = 0, onStart }: { delay?: number; duration?: number; rotate?: number; onStart?: () => void } = {},
): Animation | null {
  if (prefersReducedMotion()) {
    // No travel, but still show that something arrived.
    return el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 200, delay, fill: 'backwards' });
  }
  const to = el.getBoundingClientRect();
  if (!to.width) return null;
  const dx = from.left + from.width / 2 - (to.left + to.width / 2);
  const dy = from.top + from.height / 2 - (to.top + to.height / 2);
  const scale = from.width / to.width;
  const base = el.style.transform || '';
  const prevZ = el.style.zIndex;
  const prevPos = el.style.position;
  if (getComputedStyle(el).position === 'static') el.style.position = 'relative';
  el.style.zIndex = '60';
  const anim = el.animate(
    [
      { transform: `translate(${dx}px, ${dy}px) scale(${scale}) rotate(${rotate}deg) ${base}`, opacity: 0, offset: 0 },
      { opacity: 1, offset: 0.08 },
      { transform: `translate(0px, 0px) scale(1) rotate(0deg) ${base}`, opacity: 1, offset: 1 },
    ],
    { duration, delay, easing: EASE, fill: 'backwards' },
  );
  if (onStart) window.setTimeout(onStart, delay);
  anim.onfinish = anim.oncancel = () => {
    el.style.zIndex = prevZ;
    el.style.position = prevPos;
  };
  return anim;
}

// Flies a temporary face-down card between two points (opponent draws).
export function ghostFly(from: DOMRect, to: DOMRect, { delay = 0, duration = 420 } = {}) {
  if (prefersReducedMotion()) return;
  const w = Math.min(from.width, 60);
  const h = w * 1.42;
  const g = document.createElement('div');
  g.className = 'ghost-card';
  Object.assign(g.style, {
    left: `${from.left + from.width / 2 - w / 2}px`,
    top: `${from.top + from.height / 2 - h / 2}px`,
    width: `${w}px`,
    height: `${h}px`,
  });
  document.body.appendChild(g);
  const dx = to.left + to.width / 2 - (from.left + from.width / 2);
  const dy = to.top + to.height / 2 - (from.top + from.height / 2);
  const anim = g.animate(
    [
      { transform: 'translate(0, 0) rotate(0deg)', opacity: 1 },
      { transform: `translate(${dx}px, ${dy}px) rotate(-12deg) scale(0.6)`, opacity: 0.9 },
    ],
    { duration, delay, easing: EASE, fill: 'both' },
  );
  anim.onfinish = anim.oncancel = () => g.remove();
}

// Adds a highlight class to an element for a short time.
export function flash(selector: string, cls: string, ms: number) {
  const el = document.querySelector<HTMLElement>(selector);
  if (!el) return;
  el.classList.add(cls);
  window.setTimeout(() => el.classList.remove(cls), ms);
}
