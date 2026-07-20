import { useCallback, useState } from "react";
import { useAuth } from "react-oidc-context";

import rabbitMascot from "../assets/mascot.png";
import { SplashIntro } from "../components/landing/SplashIntro";
import { VideoPlaceholder } from "../components/landing/VideoPlaceholder";
import {
  architectureSteps,
  centralResearchQuestion,
  comparisonRows,
  evaluationLevels,
  learningPrinciples,
  researchSources,
  roleStories,
  teamMembers,
} from "../content/capstoneSiteContent";
import {
  getRedirectOrigin,
  getRedirectUri,
  hasOriginMismatch,
} from "../auth/cognitoConfig";
import type { AppView } from "../types/navigation";
import "./LandingPage.css";

interface LandingPageProps {
  onNavigate: (view: AppView) => void;
  demoMode?: boolean;
}

const SPLASH_SESSION_KEY = "codingrabbit.capstone-intro-seen";

function shouldShowSplash(): boolean {
  try {
    return window.sessionStorage.getItem(SPLASH_SESSION_KEY) !== "true";
  } catch {
    return true;
  }
}

function rememberSplashCompletion(): void {
  try {
    window.sessionStorage.setItem(SPLASH_SESSION_KEY, "true");
  } catch {
    // The public site remains usable when browser storage is unavailable.
  }
}

export function LandingPage({ onNavigate, demoMode = false }: LandingPageProps) {
  const auth = useAuth();
  const [showSplash, setShowSplash] = useState(shouldShowSplash);
  const loginDisabled = hasOriginMismatch();

  const completeSplash = useCallback(() => {
    rememberSplashCompletion();
    setShowSplash(false);
    window.requestAnimationFrame(() => {
      document.getElementById("capstone-site-title")?.focus();
    });
  }, []);

  const handleLogin = useCallback(() => {
    rememberSplashCompletion();
    void auth.signinRedirect();
  }, [auth]);

  const replayIntro = () => {
    setShowSplash(true);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  if (showSplash) {
    return (
      <SplashIntro
        loginDisabled={loginDisabled}
        onComplete={completeSplash}
        onLogin={handleLogin}
      />
    );
  }

  return (
    <div className="capstone-site">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>

      <header className="public-header">
        <a className="public-brand" href="#top" aria-label="CodingRabbit home">
          codingrabbit<span>.dev</span>
          <span className="beta-chip">MIDS capstone</span>
        </a>
        <nav className="public-nav" aria-label="Public site navigation">
          <a href="#problem">Problem</a>
          <a href="#approach">Approach</a>
          <a href="#product">Product</a>
          <a href="#evaluation">Evaluation</a>
          <a href="#team">Team</a>
        </nav>
        <button
          type="button"
          className="pill-button"
          onClick={handleLogin}
          disabled={loginDisabled}
        >
          Sign in
        </button>
      </header>

      {loginDisabled && (
        <div className="origin-warning" role="alert">
          <strong>Wrong URL for Cognito login.</strong> Open the app at{" "}
          <a href={getRedirectOrigin()}>{getRedirectOrigin()}</a>. The configured
          callback is <code>{getRedirectUri()}</code>, but this page is on{" "}
          <code>{window.location.origin}</code>.
        </div>
      )}

      <main id="main-content">
        <section id="top" className="public-hero landing-shell">
          <div className="hero-copy">
            <p className="eyebrow">UC Berkeley MIDS · Capstone project</p>
            <h1 id="capstone-site-title" tabIndex={-1}>
              Learn C++ without giving away the thinking.
            </h1>
            <p className="hero-lede">
              CodingRabbit is a course-grounded AI learning partner that meets
              students inside GitHub Codespaces, gives instructors control over
              the learning environment, and evaluates the system end to end.
            </p>
            <div className="hero-actions">
              <button
                type="button"
                className="pill-button"
                onClick={handleLogin}
                disabled={loginDisabled}
              >
                Try CodingRabbit
              </button>
              <a className="pill-link pill-link-secondary" href="#product">
                Explore the MVP
              </a>
              <a className="text-button hero-sign-in" href="#approach">
                Explore how it works
              </a>
            </div>
            <ul className="proof-list" aria-label="Product highlights">
              <li>VS Code native</li>
              <li>Course grounded</li>
              <li>Instructor governed</li>
              <li>Evaluated end to end</li>
            </ul>
          </div>

          <div className="hero-product" aria-label="CodingRabbit interaction preview">
            <div className="hero-window-bar">
              <span />
              <span />
              <span />
              <strong>codingrabbit / homework-assist</strong>
            </div>
            <div className="hero-product-body">
              <div className="hero-rabbit-panel">
                <img src={rabbitMascot} alt="CodingRabbit mascot" />
                <div className="carrot-balance">
                  <span aria-hidden="true">🥕</span>
                  <strong>20</strong>
                  <small>carrots</small>
                </div>
              </div>
              <div className="hero-conversation">
                <div className="message message-student">
                  <span>Student</span>
                  Why does this loop skip the last element?
                </div>
                <div className="message message-rabbit">
                  <span>CodingRabbit</span>
                  Trace the final comparison. What value does the condition test
                  after the last successful iteration?
                </div>
                <div className="insight-unlocked">
                  <span>Reasoning recognized</span>
                  <strong>+5 carrots</strong>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section id="problem" className="section-block landing-shell">
          <div className="section-heading section-heading-wide">
            <p className="eyebrow">The question behind the product</p>
            <h2>What happens to learning when answers become effortless?</h2>
          </div>
          <blockquote className="research-question">
            <span>Our central inquiry</span>
            “{centralResearchQuestion}”
          </blockquote>
          <div className="problem-grid">
            <article>
              <span className="problem-number">01</span>
              <h3>Help arrives too late</h3>
              <p>
                Students get stuck between office hours, precisely when timely
                feedback could keep effort productive.
              </p>
            </article>
            <article>
              <span className="problem-number">02</span>
              <h3>Generic AI optimizes for completion</h3>
              <p>
                A plausible answer can remove the reasoning practice students
                need to build durable programming capability.
              </p>
            </article>
            <article>
              <span className="problem-number">03</span>
              <h3>Instructors lose visibility</h3>
              <p>
                Unmanaged tools ignore course sequence, assignment policy, and
                the instructor's view of where support is needed.
              </p>
            </article>
          </div>
          <div className="evidence-placeholder">
            <span>Evidence placeholder</span>
            Add approved needs-assessment sample, finding, and participant quote.
          </div>
        </section>

        <section id="approach" className="section-block approach-section">
          <div className="landing-shell">
            <div className="section-heading">
              <p className="eyebrow">A broader pedagogical framework</p>
              <h2>Design the AI around the act of learning.</h2>
              <p>
                CodingRabbit combines related learning-science ideas rather than
                reducing instruction to a single conversational technique.
              </p>
            </div>
            <div className="principles-grid">
              {learningPrinciples.map((principle, index) => (
                <article className="principle-card" key={principle.title}>
                  <div className="principle-index">0{index + 1}</div>
                  <span>{principle.label}</span>
                  <h3>{principle.title}</h3>
                  <p>{principle.description}</p>
                </article>
              ))}
            </div>

            <div className="human-agency-banner">
              <div>
                <p className="eyebrow">Human agency is the constraint</p>
                <h3>AI should expand feedback, not replace judgment.</h3>
              </div>
              <p>
                The system stays inside approved course context, exposes its
                activity to instructors, and escalates to human support when
                automated help is no longer the right intervention.
              </p>
            </div>

            <div className="comparison-block">
              <div className="section-heading section-heading-wide">
                <p className="eyebrow">Established pattern, expanded system</p>
                <h2>Pedagogically aligned with the CS50 Duck, built for course governance.</h2>
                <p>
                  CS50 demonstrates the value of course-aware AI rubber-duck
                  debugging. CodingRabbit explores how that learning pattern can
                  extend into instructor-owned sections, adaptive course context,
                  gamification, analytics, and continuous evaluation.
                </p>
              </div>
              <div className="comparison-table-wrap">
                <table className="comparison-table">
                  <thead>
                    <tr>
                      <th>Capability</th>
                      <th>CS50 public precedent</th>
                      <th>CodingRabbit implementation</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparisonRows.map((row) => (
                      <tr key={row.capability}>
                        <th scope="row">{row.capability}</th>
                        <td>{row.precedent}</td>
                        <td>{row.codingRabbit}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="independence-note">
                CodingRabbit is an independent UC Berkeley MIDS capstone project.
                It is not affiliated with, endorsed by, or part of Harvard CS50.
              </p>
            </div>
          </div>
        </section>

        <section id="product" className="section-block landing-shell">
          <div className="section-heading section-heading-split">
            <div>
              <p className="eyebrow">See the MVP work</p>
              <h2>One learning loop, three coordinated experiences.</h2>
            </div>
            <p>
              The student interaction, instructor workflow, and platform
              evaluation are parts of one deployed system, not disconnected demos.
            </p>
          </div>
          <VideoPlaceholder
            eyebrow="End-to-end product overview"
            title="From a C++ bug to an evaluated learning interaction"
            description="Replace with a 75-90 second walkthrough showing extension authentication, guided debugging, a carrot reward, instructor analytics, and an offline evaluation run."
            duration="75-90 seconds"
          />

          <div className="role-grid">
            {roleStories.map((story) => (
              <article className={`role-card role-card-${story.accent}`} key={story.role}>
                <span className="role-label">For {story.role}</span>
                <h3>{story.title}</h3>
                <p>{story.description}</p>
                <ul>
                  {story.capabilities.map((capability) => (
                    <li key={capability}>{capability}</li>
                  ))}
                </ul>
                <VideoPlaceholder
                  compact
                  eyebrow={story.role}
                  title={story.videoLabel}
                  description="Final narrated workflow recording goes here."
                  duration={story.role === "Administrators" ? "60-75 seconds" : "45-60 seconds"}
                />
              </article>
            ))}
          </div>
        </section>

        <section id="gamification" className="section-block gamification-section">
          <div className="landing-shell gamification-layout">
            <div className="gamification-copy">
              <p className="eyebrow">Lightweight behavioral gamification</p>
              <h2>Reward the debugging process, not only the answer.</h2>
              <p>
                Homework Assist begins with 20 carrots. Routine help spends one;
                a recognized debugging insight earns five. The visible economy
                makes pacing understandable and creates a moment of recognition
                when the learner explains something correctly.
              </p>
              <p className="claim-boundary">
                The mechanic is implemented. Its effect on learning and
                engagement is an evaluation question, not a presumed outcome.
              </p>
              <a className="inline-link" href="#evaluation">
                See how we plan to evaluate it →
              </a>
            </div>
            <div className="carrot-journey" aria-label="Example carrot interaction">
              <div className="carrot-step">
                <span>Start the hour</span>
                <strong>20</strong>
                <small>carrots available</small>
              </div>
              <div className="carrot-connector">ordinary turn · -1</div>
              <div className="carrot-step carrot-step-low">
                <span>Ask for support</span>
                <strong>19</strong>
                <small>the cost stays visible</small>
              </div>
              <div className="carrot-connector carrot-connector-reward">
                debugging insight · +5
              </div>
              <div className="carrot-step carrot-step-win">
                <span>Explain the bug</span>
                <strong>24</strong>
                <small>reasoning is recognized</small>
              </div>
            </div>
          </div>
        </section>

        <section id="architecture" className="section-block landing-shell">
          <div className="section-heading">
            <p className="eyebrow">Governed from prompt to evidence</p>
            <h2>A learning system, not a chatbot wrapper.</h2>
            <p>
              Identity, course context, guardrails, inference, telemetry, and
              evaluation are explicit stages in the deployed workflow.
            </p>
          </div>
          <ol className="architecture-flow">
            {architectureSteps.map((step, index) => (
              <li key={step}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <strong>{step}</strong>
              </li>
            ))}
          </ol>
          <div className="diagram-placeholder">
            <span>Final diagram placeholder</span>
            Replace this block with the simplified production architecture,
            including asynchronous ingestion and evaluation workers.
          </div>
        </section>

        <section id="evaluation" className="section-block evaluation-section">
          <div className="landing-shell">
            <div className="section-heading section-heading-split">
              <div>
                <p className="eyebrow">Evaluate the learning system</p>
                <h2>Model quality is necessary. It is not sufficient.</h2>
              </div>
              <p>
                We evaluate whether students retain the cognitive work, whether
                instructors gain useful control, and whether the platform behaves
                reliably across routes and releases.
              </p>
            </div>
            <div className="evaluation-grid">
              {evaluationLevels.map((evaluation) => (
                <article key={evaluation.level}>
                  <span className="evaluation-level">Level {evaluation.level}</span>
                  <h3>{evaluation.title}</h3>
                  <p className="evaluation-question">{evaluation.question}</p>
                  <ul>
                    {evaluation.measures.map((measure) => (
                      <li key={measure}>{measure}</li>
                    ))}
                  </ul>
                </article>
              ))}
            </div>

            <div className="results-block">
              <div className="results-intro">
                <p className="eyebrow">Results and decisions</p>
                <h3>Every metric must change a decision.</h3>
                <p>
                  Final cards will report the question, dataset, sample size,
                  baseline, metric, result, product decision, and limitation.
                </p>
              </div>
              {[
                "Student learning and carrot usability",
                "Instructor workflow and analytics value",
                "Grounding, leakage, drift, and reliability",
              ].map((result) => (
                <div className="result-placeholder" key={result}>
                  <span>Final evidence pending</span>
                  <strong>{result}</strong>
                  <small>Dataset · baseline · result · decision · limitation</small>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="responsible-ai" className="section-block landing-shell">
          <div className="responsibility-grid">
            <div>
              <p className="eyebrow">Responsible use</p>
              <h2>Preserve agency. Make uncertainty visible.</h2>
            </div>
            <div className="responsibility-list">
              <article>
                <h3>Grounding is not certainty</h3>
                <p>
                  Approved retrieval reduces scope and hallucination risk, but
                  the assistant can still be wrong.
                </p>
              </article>
              <article>
                <h3>Analytics are for support</h3>
                <p>
                  Role-scoped telemetry should help instructors intervene, not
                  become punitive surveillance.
                </p>
              </article>
              <article>
                <h3>People remain part of the system</h3>
                <p>
                  Carrot exhaustion, uncertain guidance, and complex needs route
                  students toward human TAs and instructors.
                </p>
              </article>
            </div>
          </div>
        </section>

        <section id="team" className="section-block team-section">
          <div className="landing-shell">
            <div className="section-heading">
              <p className="eyebrow">Built at UC Berkeley</p>
              <h2>A MIDS capstone exploring effective learning with AI.</h2>
              <p>
                We combine learning design, applied AI, RAG, guardrails, and
                cloud infrastructure to study how AI can support learning
                without replacing the learner's own reasoning.
              </p>
            </div>
            <div className="team-grid">
              {teamMembers.map((member) => (
                <article className="team-card" key={member.name}>
                  <div className="team-portrait">
                    <img src={member.portrait} alt={`Portrait of ${member.name}`} />
                  </div>
                  <div className="team-card-copy">
                    <h3>{member.name}</h3>
                    <p>{member.contributions}</p>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="final-cta landing-shell">
          <img src={rabbitMascot} alt="" aria-hidden="true" />
          <div>
            <p className="eyebrow">The beta is live</p>
            <h2>Explore a different relationship between AI and learning.</h2>
          </div>
          <button
            type="button"
            className="pill-button pill-button-large"
            onClick={handleLogin}
            disabled={loginDisabled}
          >
            Try CodingRabbit
          </button>
        </section>

        {demoMode && (
          <section className="demo-preview landing-shell" aria-label="Development previews">
            <span>Development previews</span>
            {(["student", "professor", "admin"] as const).map((view) => (
              <button type="button" key={view} onClick={() => onNavigate(view)}>
                Open {view} view
              </button>
            ))}
          </section>
        )}
      </main>

      <footer className="public-footer">
        <div>
          <strong>codingrabbit.dev</strong>
          <span>UC Berkeley MIDS capstone · Beta</span>
        </div>
        <div className="footer-links">
          {researchSources.map((source) => (
            <a key={source.href} href={source.href} target="_blank" rel="noreferrer">
              {source.label}
            </a>
          ))}
          <button type="button" onClick={replayIntro}>
            Replay intro
          </button>
        </div>
      </footer>
    </div>
  );
}
