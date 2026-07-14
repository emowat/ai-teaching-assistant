export interface ModelOption {
  label: string;
  value: string;
}

export const CUSTOM_MODEL_VALUE = "__custom__";

export const OPENAI_MODEL_OPTIONS: ModelOption[] = [
  { label: "gpt-5.4-mini", value: "gpt-5.4-mini" },
  { label: "gpt-5.4", value: "gpt-5.4" },
  { label: "gpt-5.5", value: "gpt-5.5" },
];

export const COHERE_MODEL_OPTIONS: ModelOption[] = [
  { label: "command-r", value: "command-r" },
  { label: "command-r-plus", value: "command-r-plus" },
  { label: "command-xlarge-nightly", value: "command-xlarge-nightly" },
];

export const BEDROCK_MODEL_OPTIONS: ModelOption[] = [
  { label: "Amazon Nova 2 Lite", value: "us.amazon.nova-2-lite-v1:0" },
  {
    label: "Anthropic Claude Sonnet 4.6",
    value: "us.anthropic.claude-sonnet-4-6",
  },
  {
    label: "Anthropic Claude Haiku 4.5",
    value: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
  },
];

export const OLLAMA_MODEL_OPTIONS: ModelOption[] = [
  { label: "qwen3.5:9b", value: "qwen3.5:9b" },
  { label: "llama3.1:8b", value: "llama3.1:8b" },
  { label: "llama3.2:3b", value: "llama3.2:3b" },
];

const BEDROCK_MODEL_ALIASES: Record<string, string> = {
  "anthropic.claude-sonnet-4-6": "us.anthropic.claude-sonnet-4-6",
  "anthropic.claude-haiku-4-5": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
  "us.anthropic.claude-haiku-4-5": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
};

export function normalizeBedrockModelId(modelId: string): string {
  const value = modelId.trim();
  return BEDROCK_MODEL_ALIASES[value] ?? value;
}

export function isBedrockModelId(modelId: string): boolean {
  const normalized = normalizeBedrockModelId(modelId);
  return BEDROCK_MODEL_OPTIONS.some((option) => option.value === normalized);
}

export function getModelOptions(provider: string): ModelOption[] {
  switch (provider) {
    case "openai":
      return OPENAI_MODEL_OPTIONS;
    case "cohere":
      return COHERE_MODEL_OPTIONS;
    case "bedrock":
      return BEDROCK_MODEL_OPTIONS;
    case "ollama":
      return OLLAMA_MODEL_OPTIONS;
    case "sagemaker":
      return [];
    default:
      return [];
  }
}

export function getDefaultModel(provider: string): string {
  switch (provider) {
    case "openai":
      return OPENAI_MODEL_OPTIONS[0].value;
    case "cohere":
      return COHERE_MODEL_OPTIONS[0].value;
    case "bedrock":
      return BEDROCK_MODEL_OPTIONS[0].value;
    case "ollama":
      return OLLAMA_MODEL_OPTIONS[0].value;
    case "sagemaker":
      return "";
    default:
      return "";
  }
}

export function resolveModelValue(selected: string, customValue: string): string {
  return selected === CUSTOM_MODEL_VALUE ? customValue.trim() : selected;
}
