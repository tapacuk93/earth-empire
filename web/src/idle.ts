// Floating controls fade out after a few seconds without input and come back on any tap, move,
// key or scroll. They carry the class `fui`; this toggles `ui-idle` on <html>.
const IDLE_MS = 3500;
let timer = 0;
function wake() {
  if ((window as unknown as { __EE_NO_IDLE__?: boolean }).__EE_NO_IDLE__) return; // tests switch it off
  document.documentElement.classList.remove('ui-idle');
  clearTimeout(timer);
  timer = window.setTimeout(() => {
    // Never hide while something inside the controls has focus or a pointer is over them.
    const a = document.activeElement;
    if (a && a.closest?.('.fui, .prompt')) { wake(); return; }
    document.documentElement.classList.add('ui-idle');
  }, IDLE_MS);
}
['pointerdown', 'pointermove', 'keydown', 'wheel', 'touchstart', 'focusin'].forEach((e) => addEventListener(e, wake, { passive: true, capture: true }));
addEventListener('scroll', wake, { passive: true, capture: true });
wake();
