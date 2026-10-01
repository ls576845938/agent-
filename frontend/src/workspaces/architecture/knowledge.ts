import source from './knowledge.json';

export type ArchitectureModuleKnowledge = {
  module_id: string;
  inputs: string[];
  outputs: string[];
  upstream: string[];
  downstream: string[];
  boundary: string;
  entrypoints: string[];
};

export type ArchitectureCoreFile = {
  path: string;
  module_id: string;
  purpose: string;
  entry: string;
  consumers: string[];
  side_effects: string;
  forbidden: string;
  tests: string[];
  source_blob: string;
  source_commit: string;
};

export type ArchitectureFileGroup = {
  id: string;
  label: string;
  patterns: string[];
  modules: string[];
  purpose: string;
};

export const architectureKnowledge = source as {
  schema_version: string;
  source_commit: string;
  scope_note: string;
  modules: ArchitectureModuleKnowledge[];
  core_files: ArchitectureCoreFile[];
  file_groups: ArchitectureFileGroup[];
  safety: Record<string, boolean>;
};

export const knowledgeByModule = new Map(
  architectureKnowledge.modules.map(item => [item.module_id, item]),
);
