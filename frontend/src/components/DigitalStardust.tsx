import type { CSSProperties } from "react";

// Fixed seed arithmetic keeps server/client output identical and navigation stable.
// This server component adds no client JavaScript or animation timers.
const particles = Array.from({ length: 24 }, (_, index) => ({
  left: 2 + ((index * 37 + 11) % 96),
  size: 2 + ((index * 7) % 5),
  duration: 28 + ((index * 11) % 25),
  delay: -((index * 13 + 7) % 53),
  drift: ((index * 17) % 61) - 30,
  opacity: 0.28 + ((index * 3) % 5) * 0.07,
  color: ["#60a5fa", "#a78bfa", "#60a5fa", "#cffafe"][index % 4],
  star: index % 6 === 3,
}));

export default function DigitalStardust() {
  return (
    <div className="digital-stardust" aria-hidden="true">
      {particles.map((particle, index) => (
        <span
          key={index}
          className={`digital-stardust-particle${particle.star ? " digital-stardust-star" : ""}`}
          style={{
            left: `${particle.left}%`,
            "--dust-size": `${particle.size}px`,
            "--dust-duration": `${particle.duration}s`,
            "--dust-delay": `${particle.delay}s`,
            "--dust-drift": `${particle.drift}px`,
            "--dust-opacity": particle.opacity,
            "--dust-color": particle.color,
          } as CSSProperties}
        />
      ))}
    </div>
  );
}
