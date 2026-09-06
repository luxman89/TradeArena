export default [
  {
    files: ["scripts/ui/**/*.js", "tests/ui/**/*.js", "playwright.config.js"],
    languageOptions: { ecmaVersion: 2022, sourceType: "module" },
    rules: {
      "no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
      "no-constant-condition": "error",
      "no-unreachable": "error",
      "no-duplicate-imports": "error",
    },
  },
];
