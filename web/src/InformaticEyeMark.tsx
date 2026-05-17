import { useEffect, useId, useRef, useState } from "react";

const VB = 48;
const EYE_CX = 24;
const EYE_CY = 24;

export function InformaticEyeMark() {
  const wrapRef = useRef<HTMLSpanElement>(null);
  const [gaze, setGaze] = useState({ x: 0, y: 0 });
  const gid = useId().replace(/:/g, "");

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (mq.matches) {
      return;
    }

    const onMove = (e: MouseEvent) => {
      const el = wrapRef.current;
      if (!el) {
        return;
      }
      const r = el.getBoundingClientRect();
      const cx = r.left + r.width / 2;
      const cy = r.top + r.height / 2;
      let vx = (e.clientX - cx) / (r.width * 0.38);
      let vy = (e.clientY - cy) / (r.height * 0.38);
      const len = Math.hypot(vx, vy) || 1;
      if (len > 1) {
        vx /= len;
        vy /= len;
      }
      setGaze({ x: vx * 7.2, y: vy * 5.1 });
    };

    window.addEventListener("mousemove", onMove, { passive: true });
    return () => window.removeEventListener("mousemove", onMove);
  }, []);

  const irisId = `fe-iris-${gid}`;
  const scleraId = `fe-sclera-${gid}`;
  const glowId = `fe-glow-${gid}`;

  return (
    <span ref={wrapRef} className="sidebar-brand__mark-eye">
      <svg
        className="sidebar-brand__mark-eye-svg"
        viewBox={`0 0 ${VB} ${VB}`}
        width="100%"
        height="100%"
        aria-hidden
      >
        <defs>
          <radialGradient id={scleraId} cx="32%" cy="28%" r="78%">
            <stop offset="0%" stopColor="#f4f6ff" stopOpacity="0.98" />
            <stop offset="55%" stopColor="#dce3fb" stopOpacity="0.94" />
            <stop offset="100%" stopColor="#b8c4ee" stopOpacity="0.88" />
          </radialGradient>
          <radialGradient id={irisId} cx="35%" cy="32%" r="72%">
            <stop offset="0%" stopColor="#7ea3ff" />
            <stop offset="42%" stopColor="#3d54a8" />
            <stop offset="78%" stopColor="#14182a" />
            <stop offset="100%" stopColor="#0a0c14" />
          </radialGradient>
          <filter id={glowId} x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur stdDeviation="0.8" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <ellipse
          cx={EYE_CX}
          cy={EYE_CY}
          rx="17"
          ry="12.5"
          fill={`url(#${scleraId})`}
          stroke="rgba(255,255,255,0.22)"
          strokeWidth="0.6"
        />

        <g transform={`rotate(-8 ${EYE_CX} ${EYE_CY})`}>
          <ellipse
            cx={EYE_CX}
            cy={EYE_CY}
            rx="17.8"
            ry="13.2"
            fill="none"
            stroke="rgba(107,140,255,0.35)"
            strokeWidth="0.45"
            strokeDasharray="2.2 3.8"
            className="sidebar-brand__mark-eye-orbit"
          />
        </g>

        <g transform={`translate(${gaze.x} ${gaze.y})`}>
          <circle cx={EYE_CX} cy={EYE_CY} r="11.2" fill={`url(#${irisId})`} filter={`url(#${glowId})`} />
          {Array.from({ length: 12 }, (_, i) => {
            const a = (i / 12) * Math.PI * 2;
            const x2 = EYE_CX + Math.cos(a) * 10.2;
            const y2 = EYE_CY + Math.sin(a) * 10.2;
            const deg = Math.round((a * 180) / Math.PI);
            return (
              <line
                key={`iris-spoke-${gid}-${deg}`}
                x1={EYE_CX}
                y1={EYE_CY}
                x2={x2}
                y2={y2}
                stroke="rgba(0,0,0,0.14)"
                strokeWidth="0.35"
              />
            );
          })}
          <circle
            cx={EYE_CX}
            cy={EYE_CY}
            r="7.2"
            fill="none"
            stroke="rgba(107,140,255,0.5)"
            strokeWidth="0.5"
            strokeDasharray="1.2 2.1"
          />
          <circle cx={EYE_CX} cy={EYE_CY} r="4.1" fill="#050608" />
          <rect
            x={EYE_CX - 2.35}
            y={EYE_CY - 2.35}
            width="1.15"
            height="1.15"
            fill="#8af"
            opacity="0.85"
            rx="0.15"
          />
          <circle cx={EYE_CX + 1.9} cy={EYE_CY - 1.75} r="1.05" fill="rgba(255,255,255,0.55)" />
        </g>

        <ellipse
          cx="17"
          cy="17"
          rx="5"
          ry="3.2"
          fill="rgba(255,255,255,0.42)"
          transform="rotate(-28 17 17)"
          pointerEvents="none"
        />
      </svg>
    </span>
  );
}
