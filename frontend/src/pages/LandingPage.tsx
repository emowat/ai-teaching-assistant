import { useCallback, useState } from "react";
import { useAuth } from "react-oidc-context";

import architectureImage from "../assets/mvp-architecture.png";
import rabbitMascot from "../assets/mascot.png";
import { DemoVideo } from "../components/landing/DemoVideo";
import { SplashIntro } from "../components/landing/SplashIntro";
import {
  acknowledgements,
  architectureSteps,
  centralResearchQuestion,
  cognitiveStages,
  comparisonRows,
  evaluationLevels,
  externalMotivation,
  finalDemo,
  finalResults,
  judgeResults,
  learningPrinciples,
  participantQuotes,
  privacyCommitments,
  projectPageUrl,
  repositoryUrl,
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
          <a href="#resources">Resources</a>
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
            <p className="eyebrow">UC Berkeley MIDS · Summer 2026 capstone</p>
            <h1 id="capstone-site-title" tabIndex={-1}>
              Learn C++ without giving away the thinking.
            </h1>
            <p className="hero-lede">
              CodingRabbit is a pedagogy-first AI teaching assistant that meets
              students inside GitHub Codespaces, grounds support in approved
              course material, and gives instructors control over how assistance
              is delivered and evaluated.
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
              <li>Measured end to end</li>
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
          <aside className="motivation-evidence" aria-label="External research motivation">
            <div>
              <span>With unrestricted AI</span>
              <strong>{externalMotivation.assistedPerformance}</strong>
              <small>assisted practice performance</small>
            </div>
            <div>
              <span>After AI was removed</span>
              <strong>{externalMotivation.unassistedPerformance}</strong>
              <small>below the unaided baseline</small>
            </div>
            <p>
              {externalMotivation.description}{" "}
              <a href={externalMotivation.sourceHref} target="_blank" rel="noreferrer">
                {externalMotivation.sourceLabel} ↗
              </a>
            </p>
          </aside>
        </section>

        <section id="approach" className="section-block approach-section">
          <div className="landing-shell">
            <div className="section-heading">
              <p className="eyebrow">A broader pedagogical framework</p>
              <h2>Design the AI around the act of learning.</h2>
              <p>
                Drawing on Vygotsky's zone of proximal development and the
                assistance dilemma, CodingRabbit increases specificity only when
                the learner needs a narrower scaffold.
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

            <div className="cognitive-stage-block">
              <div>
                <p className="eyebrow">Read the learning state first</p>
                <h3>Four stages guide which scaffold comes next.</h3>
                <p>
                  The question, code structure, cursor context, and runtime state
                  help CodingRabbit choose support that fits the learner's current
                  work instead of responding to the message in isolation.
                </p>
              </div>
              <ol className="cognitive-stage-grid">
                {cognitiveStages.map((stage) => (
                  <li key={stage.stage}>
                    <span>{stage.stage}</span>
                    <strong>{stage.title}</strong>
                    <small>{stage.description}</small>
                  </li>
                ))}
              </ol>
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
          <DemoVideo
            videoId={finalDemo.id}
            href={finalDemo.href}
            title={finalDemo.title}
            description={finalDemo.description}
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
                <a
                  className="role-demo-link"
                  href={finalDemo.href}
                  target="_blank"
                  rel="noreferrer"
                >
                  See this workflow in the final demonstration ↗
                </a>
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
                The mechanic is implemented, but the pilot did not isolate its
                causal effect. The final results report overall confidence and
                system behavior without attributing gains to carrots alone.
              </p>
              <a className="inline-link" href="#evaluation">
                See the final evaluation results →
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
          <figure className="architecture-diagram">
            <a href={architectureImage} target="_blank" rel="noreferrer">
              <img
                src={architectureImage}
                alt="CodingRabbit production architecture showing authenticated online learning, offline course ingestion, Aurora registries, Qdrant retrieval, guardrails, multi-route inference, and an isolated evaluation worker."
                loading="lazy"
                decoding="async"
              />
            </a>
            <figcaption>
              The live tutoring path is isolated from asynchronous ingestion and
              evaluation work. Select the diagram to open the full-resolution view.
            </figcaption>
          </figure>
        </section>

        <section id="evaluation" className="section-block evaluation-section">
          <div className="landing-shell">
            <div className="section-heading section-heading-split">
              <div>
                <p className="eyebrow">Evaluate the learning system</p>
                <h2>Evidence at the learner, retrieval, and system levels.</h2>
              </div>
              <p>
                The final evaluation separates self-reported pilot outcomes from
                retrieval experiments and automated TA-quality judgments. Each
                result is presented with the boundary of what it can establish.
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
                <p className="eyebrow">Final results</p>
                <h3>Metrics that changed the product.</h3>
                <p>
                  Pilot feedback shaped the experience, retrieval experiments
                  changed search policy, and five judge routes tested whether the
                  assistant's behavior held across evaluators.
                </p>
              </div>
              {finalResults.map((result) => (
                <div className="result-card" key={result.title}>
                  <span>{result.kicker}</span>
                  <strong className="result-value">{result.value}</strong>
                  <h3>{result.title}</h3>
                  <p>{result.description}</p>
                  <small>{result.note}</small>
                </div>
              ))}
            </div>

            <div className="judge-results">
              <div className="judge-results-copy">
                <p className="eyebrow">One rubric, five judge routes</p>
                <h3>TA effectiveness remained high, but judge choice still mattered.</h3>
                <p>
                  The same pedagogy, correctness, grounding, and safety rubric was
                  applied per reply and per conversation. Scores are automated
                  evaluation evidence, not direct measures of student learning.
                </p>
              </div>
              <div className="judge-table-wrap">
                <table className="judge-table">
                  <thead>
                    <tr>
                      <th>Judge</th>
                      <th>TA effectiveness</th>
                      <th>Reply impact</th>
                      <th>Conversation effect</th>
                      <th>Quality drift</th>
                    </tr>
                  </thead>
                  <tbody>
                    {judgeResults.map((judge) => (
                      <tr key={`${judge.provider}-${judge.model}`}>
                        <th scope="row">
                          <strong>{judge.model}</strong>
                          <small>{judge.provider}</small>
                        </th>
                        <td>{judge.effectiveness}</td>
                        <td>{judge.impact}</td>
                        <td>{judge.conversationEffectiveness}</td>
                        <td>{judge.qualityDrift}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="participant-feedback">
              <div>
                <p className="eyebrow">Pilot participant feedback</p>
                <h3>What learners noticed while using the MVP</h3>
              </div>
              {participantQuotes.map((quote) => (
                <blockquote key={quote}>“{quote}”</blockquote>
              ))}
            </div>
          </div>
        </section>

        <section id="responsible-ai" className="section-block landing-shell">
          <div className="responsibility-grid">
            <div>
              <p className="eyebrow">Privacy and safety by design</p>
              <h2>Preserve agency and keep people accountable.</h2>
              <p>
                Grounding and guardrails reduce risk, but they do not make an AI
                tutor infallible. Consent, scoped access, and human escalation are
                therefore product behavior, not policy footnotes.
              </p>
            </div>
            <div className="responsibility-list">
              {privacyCommitments.map((commitment) => (
                <article key={commitment.title}>
                  <h3>{commitment.title}</h3>
                  <p>{commitment.description}</p>
                </article>
              ))}
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
                    <img
                      src={member.portrait}
                      alt={`Portrait of ${member.name}`}
                      loading="lazy"
                      decoding="async"
                    />
                  </div>
                  <div className="team-card-copy">
                    <h3>{member.name}</h3>
                    <p>{member.contributions}</p>
                  </div>
                </article>
              ))}
            </div>
            <div className="acknowledgements">
              <div>
                <p className="eyebrow">Acknowledgements</p>
                <h3>Built with guidance from educators, testers, and the Berkeley community.</h3>
              </div>
              <ul>
                {acknowledgements.map((acknowledgement) => (
                  <li key={acknowledgement}>{acknowledgement}</li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        <section id="resources" className="section-block resources-section">
          <div className="landing-shell resources-layout">
            <div>
              <p className="eyebrow">Final project resources</p>
              <h2>Explore the evidence, implementation, and final walkthrough.</h2>
              <p>
                The UC Berkeley School of Information project page is the
                canonical home for the final report and presentation.
              </p>
            </div>
            <div className="resource-links">
              <a href={projectPageUrl} target="_blank" rel="noreferrer">
                <span>Final report + presentation</span>
                <strong>UC Berkeley iSchool project page</strong>
                <small>Open the official capstone archive ↗</small>
              </a>
              <a href={finalDemo.href} target="_blank" rel="noreferrer">
                <span>Final demonstration</span>
                <strong>Watch CodingRabbit in action</strong>
                <small>Open the narrated MVP walkthrough ↗</small>
              </a>
              <a href={repositoryUrl} target="_blank" rel="noreferrer">
                <span>Implementation</span>
                <strong>Browse the project repository</strong>
                <small>Review the deployed system and evaluation code ↗</small>
              </a>
            </div>
          </div>
        </section>

        <section className="final-cta landing-shell">
          <img src={rabbitMascot} alt="" aria-hidden="true" />
          <div>
            <p className="eyebrow">The deployed MVP is live</p>
            <h2>Explore a different relationship between AI and learning.</h2>
          </div>
          <div className="final-cta-actions">
            <button
              type="button"
              className="pill-button pill-button-large"
              onClick={handleLogin}
              disabled={loginDisabled}
            >
              Try CodingRabbit
            </button>
            <a
              className="pill-link pill-link-secondary"
              href={projectPageUrl}
              target="_blank"
              rel="noreferrer"
            >
              View final project
            </a>
          </div>
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
          <span>UC Berkeley MIDS capstone · Summer 2026</span>
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
