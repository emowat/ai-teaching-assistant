export interface LearningPrinciple {
  label: string;
  title: string;
  description: string;
}

export interface RoleStory {
  role: string;
  accent: "orange" | "blue" | "green";
  title: string;
  description: string;
  capabilities: readonly string[];
  videoLabel: string;
}

export interface EvaluationLevel {
  level: string;
  title: string;
  question: string;
  measures: readonly string[];
}

export interface ComparisonRow {
  capability: string;
  precedent: string;
  codingRabbit: string;
}

export const centralResearchQuestion =
  "When powerful LLM assistance is always available, how can technology help students learn effectively without outsourcing the thinking that creates durable knowledge and independent problem-solving skill?";

export const learningPrinciples: readonly LearningPrinciple[] = [
  {
    label: "Next achievable step",
    title: "Support within the learner's developing capability",
    description:
      "Vygotsky's zone of proximal development informs how CodingRabbit targets work a learner can complete with appropriate support, rather than completing the task for them.",
  },
  {
    label: "Explain the why",
    title: "Turn debugging into self-explanation",
    description:
      "Prompts ask students to inspect behavior, assumptions, and evidence. The goal is to make reasoning visible so a fix becomes reusable understanding.",
  },
  {
    label: "Adaptive support",
    title: "Scaffold without erasing productive struggle",
    description:
      "Homework and Study modes adjust the kind of help available while course context, instructor controls, and human escalation keep assistance bounded.",
  },
] as const;

export const roleStories: readonly RoleStory[] = [
  {
    role: "Students",
    accent: "orange",
    title: "Help where the learning happens",
    description:
      "CodingRabbit lives inside VS Code and uses the active course, week, editor, and terminal context to guide the next step.",
    capabilities: [
      "Cognito-authenticated Codespaces workflow",
      "Homework Assist and Study Assist modes",
      "Course-grounded references and guardrails",
      "Carrot rewards for productive debugging insights",
    ],
    videoLabel: "Student extension walkthrough",
  },
  {
    role: "Professors",
    accent: "blue",
    title: "Make AI follow the teaching plan",
    description:
      "Instructors control sections, weekly references, availability, and rosters, then inspect section and student activity without reading every conversation.",
    capabilities: [
      "Section-scoped access and invitations",
      "Weekly teaching plans and references",
      "Launch and availability controls",
      "Section and individual learning analytics",
    ],
    videoLabel: "Professor workflow walkthrough",
  },
  {
    role: "Administrators",
    accent: "green",
    title: "Operate and evaluate the full system",
    description:
      "Administrators manage the learning environment, inspect system health, and run offline evaluations without interrupting live tutoring.",
    capabilities: [
      "Users, sections, courses, and ingestion",
      "Runtime model and provider configuration",
      "Guardrail and diagnostic test surfaces",
      "On-demand offline evaluation workers",
    ],
    videoLabel: "Admin and evaluation walkthrough",
  },
] as const;

export const comparisonRows: readonly ComparisonRow[] = [
  {
    capability: "Learning pattern",
    precedent: "AI-supported rubber-duck debugging and conceptual help",
    codingRabbit:
      "Guided questions, self-explanation prompts, and separate Homework and Study modes",
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
      "A visible carrot economy rewards productive debugging insights and paces Homework Assist",
  },
] as const;

export const evaluationLevels: readonly EvaluationLevel[] = [
  {
    level: "01",
    title: "Student learning and engagement",
    question:
      "Does assistance help students make a productive next move while preserving their own reasoning?",
    measures: [
      "Debugging progress and self-explanation quality",
      "Mode transitions and time to productive next step",
      "Carrot rewards, exhaustion, return, and student sentiment",
    ],
  },
  {
    level: "02",
    title: "Instructor value and insight",
    question:
      "Can instructors govern AI support and identify where their students need human intervention?",
    measures: [
      "Section and teaching-plan workflow completion",
      "Usefulness of student and section analytics",
      "Instructor trust, control, and time saved",
    ],
  },
  {
    level: "03",
    title: "Model and platform quality",
    question:
      "Does the system remain grounded, policy-aligned, reliable, and measurable across model routes?",
    measures: [
      "Instructional-policy and leakage checks",
      "Retrieval relevance and citation quality",
      "Drift, latency, reliability, and operational health",
    ],
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
  "Aurora and offline evaluation",
] as const;

export const researchSources = [
  {
    label: "UNESCO guidance on generative AI in education",
    href: "https://www.unesco.org/en/articles/guidance-generative-ai-education-and-research?hub=66580",
  },
  {
    label: "Chi et al. on self-explanation and problem solving",
    href: "https://doi.org/10.1207/s15516709cog1302_1",
  },
  {
    label: "CS50 notes on its AI rubber duck debugger",
    href: "https://cs50.harvard.edu/college/2025/fall/notes/ai/",
  },
] as const;
