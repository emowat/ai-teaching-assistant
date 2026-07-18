interface VideoPlaceholderProps {
  eyebrow: string;
  title: string;
  description: string;
  duration: string;
  compact?: boolean;
}

export function VideoPlaceholder({
  eyebrow,
  title,
  description,
  duration,
  compact = false,
}: VideoPlaceholderProps) {
  return (
    <div className={`video-placeholder${compact ? " video-placeholder-compact" : ""}`}>
      <div className="video-placeholder-grid" aria-hidden="true" />
      <div className="video-placeholder-content">
        <span className="video-kicker">{eyebrow}</span>
        <span className="play-mark" aria-hidden="true">
          ▶
        </span>
        <h3>{title}</h3>
        <p>{description}</p>
        <span className="video-duration">Video placeholder · {duration}</span>
      </div>
    </div>
  );
}
