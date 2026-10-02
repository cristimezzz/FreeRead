module.exports = {
  forbidden: [
    { name: 'no-circular', severity: 'error', from: {}, to: { circular: true } },
    { name: 'renderer-core-types-only', severity: 'error',
      from: { path: '^apps/desktop/src/renderer' },
      to: { path: '^packages/core', dependencyTypesNot: ['type-only'] } },
    { name: 'core-no-ui-or-runtime', severity: 'error', from: { path: '^packages/core' },
      to: { path: '(^apps/|^packages/(?!core/)|node:|^(electron|react|fs|net|child_process)$)' } },
  ],
  options: { doNotFollow: { path: 'node_modules' }, exclude: '(^|/)(dist|out)/', tsPreCompilationDeps: true,
    tsConfig: { fileName: 'tsconfig.base.json' },
    enhancedResolveOptions: { exportsFields: ['exports'], conditionNames: ['types', 'import', 'default'] } },
};
