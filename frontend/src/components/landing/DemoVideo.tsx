import { useState } from "react";

interface DemoVideoProps {
  videoId: string;
  href: string;
  title: string;
  description: string;
}

export function DemoVideo({
  videoId,
  href,
  title,
  description,
}: DemoVideoProps) {
  const [isPlaying, setIsPlaying] = useState(false);

  if (isPlaying) {
    return (
      <div className="demo-video demo-video-playing">
        <iframe
          src={`https://www.youtube-nocookie.com/embed/${videoId}?autoplay=1&rel=0`}
          title={title}
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
          allowFullScreen
        />
      </div>
    );
  }

  return (
    <div className="demo-video">
      <div className="demo-video-grid" aria-hidden="true" />
      <div className="demo-video-content">
        <span className="video-kicker">Final MVP demonstration</span>
        <button
          type="button"
          className="play-mark"
          onClick={() => setIsPlaying(true)}
          aria-label={`Play ${title}`}
        >
          <span aria-hidden="true">▶</span>
        </button>
        <h3>{title}</h3>
        <p>{description}</p>
        <a href={href} target="_blank" rel="noreferrer">
          Watch on YouTube ↗
        </a>
      </div>
    </div>
  );
}
