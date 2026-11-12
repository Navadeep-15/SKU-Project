# AI Assistance and Prompt History

## 1. Overview

StockLens was developed using an AI-assisted development approach, with ChatGPT and GitHub Copilot supporting different stages of the project.

AI tools were used extensively for planning, implementation, debugging, testing, and documentation. My involvement primarily focused on understanding the project requirements, communicating implementation instructions through prompts, examining the generated results, and directing further changes as the project progressed.

This document describes how AI was used, the nature of my involvement, and the available prompt history.

## 2. AI Tools Used

### ChatGPT

ChatGPT was used for:

- Understanding and interpreting the project requirements.
- Discussing the technology stack and solution approach.
- Breaking the project into implementation phases.
- Preparing instructions for GitHub Copilot.
- Understanding technical concepts and implementation decisions.
- Reviewing project progress and identifying areas requiring further attention.
- Preparing documentation and submission guidance.

### GitHub Copilot

GitHub Copilot was used extensively for:

- Generating and modifying Python code.
- Implementing data generation and database-related functionality.
- Developing forecasting and replenishment logic.
- Creating the Streamlit dashboard.
- Implementing validation scenarios.
- Generating automated tests.
- Debugging errors and refining existing functionality.
- Preparing technical documentation and repository changes.

AI assistance was a substantial part of the development process.

## 3. My Role in the Development Process

My involvement was primarily focused on guiding the development process rather than manually implementing every component.

I started with the provided business problem and used AI tools to explore how the required functionality could be implemented.

As the project progressed, I provided prompts describing the features, requirements, and changes I wanted. I used the resulting outputs to decide what to work on next and requested further changes when necessary.

My involvement included:

- Understanding the business problem and expected project deliverables.
- Providing instructions and requirements through AI prompts.
- Choosing to use Python, Streamlit, and Supabase PostgreSQL for the project.
- Guiding development through multiple implementation phases.
- Requesting refinements to the application interface and functionality.
- Using AI assistance to investigate implementation issues.
- Examining generated outputs and available test reports.
- Preparing the repository and documentation for evaluator use.

Much of the source code, automated testing, and documentation was generated or modified with GitHub Copilot assistance.

I do not claim to have independently written every component or manually verified every line of generated code.

## 4. Development Approach

The project followed an iterative AI-assisted workflow.

**Requirement understanding:** The original problem statement was used to identify the required entities, forecasting functionality, replenishment constraints, exception scenarios, and evaluation expectations.

**Implementation planning:** ChatGPT helped organize the work into smaller implementation phases and prepare prompts for GitHub Copilot.

**Code generation:** GitHub Copilot generated and modified application code based on the provided instructions and existing project structure.

**Iteration and refinement:** Additional prompts were used to request changes, resolve reported issues, improve the interface, and address requirements identified during reviews.

**Testing and documentation:** AI-assisted tools were used to create tests, execute validation commands, summarize results, and prepare supporting documentation.

The development process relied on repeated prompting and refinement rather than entirely manual coding.

## 5. Representative Prompt History

The following excerpts represent prompts used during development. They illustrate the progression of the project but do not constitute a complete conversation export.

| Prompt excerpt | Purpose |
|---|---|
| "Based on our agreed project requirements, create the initial folder structure for the SKU-Location Demand Forecasting & Replenishment System." | Initial project structure |
| "Continue with Phase 9A: Build the Streamlit Dashboard for the existing SKU–Location Demand Forecasting & Replenishment System." | Dashboard implementation |
| "Continue with Phase 9B: Streamlit Dashboard UI/UX Refinement." | User interface refinement |
| "Update the existing Streamlit frontend branding and user-facing terminology." | StockLens branding |
| "StockLens — Complete Original Requirements Verification" | Requirements coverage review |
| "StockLens — Final Submission Polish" | Final improvements and documentation |
| "StockLens — Final YottaFlex Submission Preparation" | Submission readiness |

These are representative excerpts from the available project conversation. They are not presented as a complete record of all prompts submitted to ChatGPT and GitHub Copilot.

### Additional Prompt Records

The full historical ChatGPT and GitHub Copilot conversation exports are not included in this document.

Additional original prompts or conversation exports can be added if available. No missing prompts have been reconstructed or invented.

## 6. Testing and Validation

The repository includes automated tests covering major project components, including:

- Synthetic data generation.
- Demand forecasting.
- Replenishment recommendations.
- Database-related operations.
- Anomaly detection and validation.
- Dashboard functionality.
- Store evaluation.

GitHub Copilot was used to assist with implementing tests and running test commands.

The resulting test reports were used to assess whether the implementation satisfied the expected requirements.

Automated tests and their results are available through the repository's test files and supporting documentation. The latest results can be reproduced using the instructions in `README.md`.

The project also includes requirements-compliance documentation and database validation utilities.

A successful automated test run does not guarantee that every possible scenario has been tested. Fresh PostgreSQL initialization and application execution should be verified using the evaluator setup instructions.

## 7. Technical Decisions and Limitations

The project uses Python and Streamlit to provide a straightforward implementation of the required forecasting and replenishment workflow.

PostgreSQL, hosted through Supabase during development, provides relational storage for the project's entities and operational records.

The forecasting implementation uses baseline and weekday-seasonal methods, while replenishment recommendations consider inventory position, demand, lead time, safety stock, supplier ordering constraints, and product eligibility.

These implementations were developed with substantial AI assistance.

The solution is intended to demonstrate the required business workflow rather than serve as a production-ready inventory management platform.

Known limitations and remaining verification requirements are described in the repository's technical documentation.

## 8. Summary of AI Involvement

StockLens is an AI-assisted project in which ChatGPT and GitHub Copilot contributed significantly to the implementation.

My role centered on understanding the requirements, directing development through prompts, requesting changes, and examining the resulting application and reports.

The source code, tests, and documentation reflect an iterative development process supported extensively by AI tools.

This disclosure is intended to provide a clear account of that development approach without overstating either independent coding work or the extent of manual verification.