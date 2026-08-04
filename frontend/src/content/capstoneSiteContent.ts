import alexAlvarezPortrait from "../assets/team/alex-alvarez.png";
import carlosSchruppPortrait from "../assets/team/carlos-schrupp.png";
import ericMowatPortrait from "../assets/team/eric-mowat.png";
import ligongZhangPortrait from "../assets/team/ligong-zhang.png";
import lynWangPortrait from "../assets/team/lyn-wang.png";

export interface LearningPrinciple {
  label: string;
  title: string;
  description: string;
}

export interface CognitiveStage {
  stage: string;
  title: string;
  description: string;
}

export interface RoleStory {
  role: string;
  accent: "orange" | "blue" | "green";
  title: string;
  description: string;
  capabilities: readonly string[];
}

export interface EvaluationLevel {
  level: string;
  title: string;
  question: string;
  measures: readonly string[];
}

export interface FinalResult {
  kicker: string;
  value: string;
  title: string;
  description: string;
  note: string;
}

export interface JudgeResult {
  provider: string;
  model: string;
  effectiveness: string;
  impact: string;
  conversationEffectiveness: string;
  qualityDrift: string;
}

export interface ComparisonRow {
  capability: string;
  precedent: string;
  codingRabbit: string;
}

export interface TeamMember {
  name: string;
  contributions: string;
  portrait: string;
}

export const finalDemo = {
  id: "bWv3M2eNa4c",
  href: "https://youtu.be/bWv3M2eNa4c",
  title: "CodingRabbit final MVP demonstration",
  description:
    "Follow a student from authenticated VS Code support through instructor insight and offline system evaluation.",
} as const;

export const projectPageUrl =
  "https://www.ischool.berkeley.edu/programs/mids/capstone/2026b-summer/coding-rabbit-ai-teaching-assistant-c-courses-and-beyond";

export const repositoryUrl =
  "https://github.com/emowat/ai-teaching-assistant";

export const centralResearchQuestion =
  "When powerful LLM assistance is always available, how can technology help students learn effectively without outsourcing the thinking that creates durable knowledge and independent problem-solving skill?";

export const externalMotivation = {
  assistedPerformance: "+48%",
  unassistedPerformance: "−17%",
  description:
    "In a controlled high-school mathematics study, unrestricted AI improved assisted practice performance, but students later performed below the unaided baseline when the assistant was removed.",
  sourceLabel: "Bastani et al., PNAS (2025)",
  sourceHref: "https://doi.org/10.1073/pnas.2422633122",
} as const;

export const learningPrinciples: readonly LearningPrinciple[] = [
  {
    label: "Start broad",
    title: "Conceptual hints",
    description:
      "Point to the idea or relationship the student is missing without supplying the code that completes the assignment.",
  },
  {
    label: "Make state visible",
    title: "Visual explanations",
    description:
      "Use diagrams and concrete traces when memory, control flow, or runtime state is easier to understand visually.",
  },
  {
    label: "Narrow only when needed",
    title: "Targeted suggestions",
    description:
      "Offer a short, bounded syntax suggestion only after earlier scaffolds have not moved the learner forward.",
  },
] as const;

export const cognitiveStages: readonly CognitiveStage[] = [
  {
    stage: "01",
    title: "Conceptualizing",
    description: "Building a mental model and choosing an approach.",
  },
  {
    stage: "02",
    title: "Implementing",
    description: "Translating an approach into working C++.",
  },
  {
    stage: "03",
    title: "Restructuring",
    description: "Improving code structure without changing behavior.",
  },
  {
    stage: "04",
    title: "Debugging",
    description: "Explaining and correcting unexpected behavior.",
  },
] as const;

export const roleStories: readonly RoleStory[] = [
  {
    role: "Students",
    accent: "orange",
    title: "Help where the learning happens",
    description:
      "CodingRabbit lives inside VS Code and combines the question with active course, week, editor, cursor, and terminal context.",
    capabilities: [
      "Cognito-authenticated GitHub Codespaces workflow",
      "Homework Assist and Study Assist modes",
      "Cognitive-stage diagnosis and calibrated scaffolds",
      "Carrot rewards for productive debugging insights",
    ],
  },
  {
    role: "Professors",
    accent: "blue",
    title: "Make AI follow the teaching plan",
    description:
      "Instructors govern sections, weekly references, student availability, and rosters, then inspect class and individual activity.",
    capabilities: [
      "Section-scoped access and Cognito invitations",
      "Weekly teaching plans and references",
      "Launch, availability, and red-flag controls",
      "Section and individual learning analytics",
    ],
  },
  {
    role: "Administrators",
    accent: "green",
    title: "Operate and evaluate the full system",
    description:
      "Administrators manage the deployed learning environment and run reproducible offline evaluations without interrupting live tutoring.",
    capabilities: [
      "Users, sections, courses, and ingestion",
      "Runtime model and provider configuration",
      "Guardrail and diagnostic test surfaces",
      "On-demand evaluation workers and result artifacts",
    ],
  },
] as const;

export const comparisonRows: readonly ComparisonRow[] = [
  {
    capability: "Learning pattern",
    precedent: "AI-supported rubber-duck debugging and conceptual help",
    codingRabbit:
      "Cognitive-stage diagnosis with conceptual, visual, and targeted scaffold forms",
  },
  {
    capability: "Course grounding",
    precedent: "Course-specific policy and recent course context",
    codingRabbit:
      "Course-scoped retrieval plus professor-controlled weekly references",
  },
  {
    capability: "Learning environment",
    precedent: "Available through the CS50 learning environment",
    codingRabbit:
      "A native VS Code extension in GitHub Codespaces with editor and terminal context",
  },
  {
    capability: "Instructor governance",
    precedent: "A staff-defined course experience",
    codingRabbit:
      "Sections, memberships, teaching plans, week availability, analytics, and launch controls",
  },
  {
    capability: "Motivation and pacing",
    precedent: "No comparison claim based on currently cited public material",
    codingRabbit:
      "A visible carrot economy recognizes productive debugging insights and paces Homework Assist",
  },
] as const;

export const evaluationLevels: readonly EvaluationLevel[] = [
  {
    level: "01",
    title: "Pilot learner experience",
    question:
      "How did participants describe their confidence before and after using the deployed MVP?",
    measures: [
      "Debugging confidence: 3.0 to 3.9 (+29.3%)",
      "Problem comprehension: 3.0 to 3.8 (+28.4%)",
      "Overall C++ confidence: 3.0 to 3.8 (+27.6%)",
    ],
  },
  {
    level: "02",
    title: "Retrieval and policy behavior",
    question:
      "Did course retrieval and guardrail decisions improve grounding without blocking legitimate learning?",
    measures: [
      "Retrieval recall increased from 53% to 65%",
      "Retrieval precision increased from 27% to 32%",
      "Input blocking narrowed to deterministic high-confidence rules",
    ],
  },
  {
    level: "03",
    title: "TA and platform quality",
    question:
      "Did independent judge routes agree that the assistant remained pedagogically useful, correct, grounded, and safe?",
    measures: [
      "72 turns across 14 evaluated sessions",
      "TA effectiveness ranged from 0.88 to 0.97 across five judges",
      "Approximately 96% cross-judge agreement",
    ],
  },
] as const;

export const finalResults: readonly FinalResult[] = [
  {
    kicker: "Pilot confidence",
    value: "+29.3%",
    title: "Debugging confidence",
    description:
      "Average self-reported debugging confidence increased from 3.0 to 3.9 on a five-point scale.",
    note: "Pilot pre/post survey; not a causal retention result",
  },
  {
    kicker: "Conditional retrieval",
    value: "53% → 65%",
    title: "Relevant context recall",
    description:
      "Selective C++ reference search improved recall while precision moved from 27% to 32%.",
    note: "LLM-as-judge retrieval experiment",
  },
  {
    kicker: "Five judge routes",
    value: "0.88–0.97",
    title: "TA effectiveness",
    description:
      "Per-reply impact and per-conversation effectiveness were evaluated with one shared rubric.",
    note: "72 turns · 14 sessions · about 96% cross-judge agreement",
  },
] as const;

export const judgeResults: readonly JudgeResult[] = [
  {
    provider: "Amazon",
    model: "Nova 2 Lite",
    effectiveness: "0.97",
    impact: "0.94",
    conversationEffectiveness: "1.00",
    qualityDrift: "0.07",
  },
  {
    provider: "OpenAI",
    model: "GPT-4o mini",
    effectiveness: "0.94",
    impact: "0.96",
    conversationEffectiveness: "0.93",
    qualityDrift: "0.00",
  },
  {
    provider: "Google",
    model: "Gemini 3.1 Flash-Lite",
    effectiveness: "0.94",
    impact: "0.94",
    conversationEffectiveness: "0.93",
    qualityDrift: "0.00",
  },
  {
    provider: "Anthropic",
    model: "Claude Haiku 4.5",
    effectiveness: "0.92",
    impact: "0.85",
    conversationEffectiveness: "1.00",
    qualityDrift: "0.00",
  },
  {
    provider: "Anthropic",
    model: "Claude Sonnet 4.6",
    effectiveness: "0.88",
    impact: "0.83",
    conversationEffectiveness: "0.93",
    qualityDrift: "0.14",
  },
] as const;

export const participantQuotes = [
  "It very often helped me understand exactly what each part of my code was doing. This helped me make changes easier.",
  "It pointed out errors in my code before I noticed them.",
  "Good job. Pretty impressive result delivered in such a short time.",
] as const;

export const privacyCommitments = [
  {
    title: "Affirmative and reversible consent",
    description:
      "Students choose whether their course interactions are stored and can withdraw consent or request deletion.",
  },
  {
    title: "Section-scoped access",
    description:
      "Professors see student analytics only for sections they are assigned to, while students retain access to their own activity.",
  },
  {
    title: "Accountable safety reports",
    description:
      "Students can raise a red flag when an interaction feels wrong, and the responsible professor must acknowledge it.",
  },
  {
    title: "Support, not surveillance",
    description:
      "Telemetry is designed to identify where human help is needed, not to become an automated disciplinary score.",
  },
] as const;

export const architectureSteps = [
  "VS Code and web clients",
  "Cognito identity",
  "FastAPI orchestration",
  "Input guardrails",
  "Course-scoped retrieval",
  "Model routing",
  "Output guardrails",
  "Aurora telemetry and offline evaluation",
] as const;

export const teamMembers: readonly TeamMember[] = [
  {
    name: "Carlos Schrupp",
    contributions: "Infrastructure, AWS backend, and UI",
    portrait: carlosSchruppPortrait,
  },
  {
    name: "Alex Alvarez",
    contributions: "Project manager, chief facilitator, and model evaluation",
    portrait: alexAlvarezPortrait,
  },
  {
    name: "Ligong Zhang",
    contributions: "Model guardrails",
    portrait: ligongZhangPortrait,
  },
  {
    name: "Lyn Wang",
    contributions: "RAG pipeline, including embeddings, vector database, and retrieval",
    portrait: lynWangPortrait,
  },
  {
    name: "Eric Mowat",
    contributions:
      "Team lead, synthetic transcripts, PEFT training, and analytics/privacy UI",
    portrait: ericMowatPortrait,
  },
] as const;

export const acknowledgements = [
  "Subject matter experts: John DeNero, Ashley Herrera, and Matthew Wagner",
  "Beta testers: Ashley Herrera, Koreen Paterson, Jonathan Mowat, and Kevin Guan",
  "Privacy and security: Rekha Venkatakrishnan",
  "Berkeley instructors: Joyce Shen and Korin Reid",
] as const;

export const researchSources = [
  {
    label: "Final CodingRabbit project page",
    href: projectPageUrl,
  },
  {
    label: "Bastani et al. on generative AI and learning",
    href: externalMotivation.sourceHref,
  },
  {
    label: "Koedinger and Aleven on the assistance dilemma",
    href: "https://doi.org/10.1007/s10648-007-9049-0",
  },
  {
    label: "CS50 notes on its AI rubber duck debugger",
    href: "https://cs50.harvard.edu/college/2025/fall/notes/ai/",
  },
] as const;
