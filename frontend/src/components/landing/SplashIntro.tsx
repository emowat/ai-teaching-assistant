import { useEffect } from "react";

import rabbitMascot from "../../assets/mascot.png";

interface SplashIntroProps {
  loginDisabled: boolean;
  onComplete: () => void;
  onLogin: () => void;
}

export const SPLASH_DURATION_MS = 10_000;

export function SplashIntro({
  loginDisabled,
  onComplete,
  onLogin,
}: SplashIntroProps) {
  useEffect(() => {
    const timeoutId = window.setTimeout(onComplete, SPLASH_DURATION_MS);
    return () => window.clearTimeout(timeoutId);
  }, [onComplete]);

  return (
    <main className="capstone-splash" aria-labelledby="splash-title">
      <div className="splash-orbit splash-orbit-one" aria-hidden="true" />
      <div className="splash-orbit splash-orbit-two" aria-hidden="true" />

      <div className="splash-actions">
        <button type="button" className="text-button" onClick={onComplete}>
          Skip intro
        </button>
        <button
          type="button"
          className="pill-button pill-button-secondary"
          onClick={onLogin}
          disabled={loginDisabled}
        >
          Sign in
        </button>
      </div>

      <div className="splash-stage">
        <div className="splash-brand">codingrabbit.dev</div>
        <img
          className="splash-mascot"
          src={rabbitMascot}
          alt="CodingRabbit mascot at a laptop"
        />
        <p className="eyebrow">Learning in the age of AI</p>
        <h1 id="splash-title">Get unstuck without giving away the thinking.</h1>
        <p className="splash-subtitle">
          A course-grounded AI learning partner for C++ inside the IDE.
        </p>

        <div className="splash-insight" aria-label="Carrot reward example">
          <span>Trace the condition</span>
          <span className="splash-arrow" aria-hidden="true">
            →
          </span>
          <strong>Explain the bug</strong>
          <span className="carrot-reward">+5 carrots</span>
        </div>
      </div>

      <div
        className="splash-progress"
        role="progressbar"
        aria-label="Introduction progress"
        aria-valuemin={0}
        aria-valuemax={10}
      >
        <span />
      </div>
    </main>
  );
}
