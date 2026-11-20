export default function celebrate(button) {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const layer = document.createElement('div');
  layer.className = 'celebration';
  layer.setAttribute('aria-hidden', 'true');
  document.body.append(layer);
  const rect = button.getBoundingClientRect();
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  const colors = ['#6366f1', '#8b5cf6', '#38bdf8', '#fbbf24', '#ec4899', '#34d399'];
  const flights = [];
  const burstScale = 1.5;
  function burst(x, y, count, reach, delay, sparks) {
    for (let i = 0; i < count; i++) {
      const angle = (i + Math.random() * .6) / count * Math.PI * 2;
      const radius = reach * burstScale * (.55 + Math.random() * .45);
      const dx = Math.cos(angle) * radius;
      const dy = Math.sin(angle) * radius;
      const piece = document.createElement('i');
      piece.style.left = x + 'px';
      piece.style.top = y + 'px';
      piece.style.background = colors[i % colors.length];
      if (sparks) piece.className = 'spark';
      layer.append(piece);
      const rotation = angle * 180 / Math.PI + 90;
      const spin = sparks ? 0 : Math.random() * 460 - 230;
      const drop = (sparks ? 8 : 58) * burstScale;
      const frames = [
        { transform: 'rotate(' + rotation + 'deg) scale(.3)', opacity: 0 },
        { opacity: 1, offset: .1 },
        { transform: 'translate(' + dx * .8 + 'px,' + dy * .8 + 'px) rotate(' + (rotation + spin / 2) + 'deg)', opacity: 1, offset: .55 },
        { transform: 'translate(' + dx + 'px,' + (dy + drop) + 'px) rotate(' + (rotation + spin) + 'deg) scale(.45)', opacity: 0 }
      ];
      flights.push(piece.animate(frames, {
        duration: (sparks ? 620 : 1150) + Math.random() * 260,
        delay, easing: 'ease-out', fill: 'both'
      }).finished);
    }
  }
  burst(cx, cy, 44, 155, 0, false);
  burst(cx - 68 * burstScale, cy - 38 * burstScale, 14, 47, 170, true);
  burst(cx + 55 * burstScale, cy + 18 * burstScale, 14, 39, 300, true);
  Promise.allSettled(flights).then(() => layer.remove());
}
