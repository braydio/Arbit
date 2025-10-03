Development Roadmap for Arbit Crypto Arbitrage System
Profitability-Focused Enhancements

Triangular Arbitrage Execution Optimizations: Refine the core triangular strategy to ensure only genuinely profitable cycles trigger trades. This means incorporating exchange fees and realistic slippage into the profit calculation, instead of assuming frictionless trades
GitHub
. Implement robust partial-fill handling and atomic execution logic: if one leg of the triangle fails or only partially fills, the system should immediately cancel the remaining orders to avoid ending up with unhedged currency positions
GitHub
. Use Immediate-Or-Cancel (IOC) limit orders and per-leg safety checks (like minimum notional trade size and maximum slippage thresholds) so that no trade executes outside of safe bounds
GitHub
. These safeguards will prevent false-positive signals and ensure that each executed triangle has a high likelihood of net positive profit after all costs.

Real-Time Market Data via WebSockets: Improve data latency and accuracy by switching from polling REST APIs to WebSocket order book streams wherever possible. Faster price updates reduce the chance that an arbitrage opportunity disappears before the bot can act. Implement per-exchange streaming feeders (e.g. using Kraken’s ccxt.pro and Alpaca’s native streams) that maintain an in-memory top-of-book with live updates
GitHub
. Include a fallback to REST whenever a stream lags or disconnects, along with staleness detection metrics to trigger alerts if data is too old
GitHub
. By ensuring 99% of cycles use up-to-date WebSocket quotes (with sub-second staleness)
GitHub
, the system can react quicker to fleeting arbitrage gaps, increasing the consistency of profitable captures.

Multi-Symbol Support and Diversification: Expand the bot to monitor multiple triangular pairs concurrently instead of a single hard-coded cycle. Configure a list of promising triangles per exchange (e.g. ETH/BTC/USDT, SOL/BTC/USDT, USDT/USDC/ETH, etc.) and implement a rotation or ranking policy to focus on the most profitable opportunity at any given moment
GitHub
. Emphasize high-liquidity cycles – for example, triangles involving major coins or popular stablecoins tend to have tight spreads and frequent micro-inefficiencies (as seen with the included SOL/BTC/USDT and USDT/USDC/ETH cycles)
GitHub
GitHub
. The system should track available inventory in each asset and enforce per-asset caps; for instance, avoid using more than a certain amount of capital on one triangle if it would deplete funds needed for another
GitHub
. By diversifying across multiple triangles and dynamically picking the best one, the bot can increase the number of profitable trades while spreading risk.

Cross-Exchange Arbitrage and Hedging: Plan a major extension to capture price discrepancies across different exchanges (Phase 3 of the project)
GitHub
. This involves monitoring the order books of multiple venues simultaneously for cases where an asset is priced lower on one exchange and higher on another, and executing buy/sell orders on each exchange to lock in the spread. Implement an exchange-agnostic routing engine that can coordinate orders on two (or more) venues, with a hedger module to manage any inventory imbalances or partial fills
GitHub
. For example, if a buy on Exchange A fills but the sell on Exchange B only partially fills, the hedger logic should immediately adjust (perhaps by selling the remainder on a secondary market or using a market order stop-gap) to minimize risk. Cross-exchange arbitrage demands very low latency and sufficient capital on each exchange, so include safeguards: use client order IDs for idempotency and a retry strategy for orders, and possibly employ an atomic execution approach (e.g. executing trades only if both legs can be confirmed)
GitHub
. While complex, this implementation can yield larger, more consistent profits whenever markets diverge, complementing the intra-exchange triangular strategy.

Optional – Idle Capital Yield Integration: To maximize overall profitability, integrate a strategy to deploy idle funds into low-risk yield opportunities when arbitrage opportunities are scarce. For instance, if the bot primarily holds USD stablecoins while waiting for trades, it could automatically supply excess capital to a DeFi lending protocol (like Aave) or a trusted yield source and withdraw when needed for a trade
GitHub
. This “yield farming module” should operate within safe parameters – e.g. only deploy funds above a reserve threshold and only into highly liquid, reputable platforms – and be able to recall funds instantly or on short notice. This approach turns waiting time into additional profit and aligns with the project’s idea of an automated stablecoin allocator with thresholds
GitHub
, without distracting from the primary arbitrage focus.

Usability and Codebase Improvements

Code Refactoring and Modularity: Continue improving the code organization to keep the project maintainable as it grows in complexity. Although the system is already structured as a modular Python package, further refactoring may be needed to isolate new functionalities. For example, separate concerns for exchange-agnostic logic vs. exchange-specific adapters, and for different strategy types (triangular vs. cross-exchange) into distinct modules or classes. Enforce a clean coding style and standards across the codebase – adopting automated linters/formatters (e.g. Ruff, Black) and type-checking will maintain consistency
GitHub
. Ensuring the code is easy to read and modify (with clear abstractions for things like the execution engine, data feed, and risk management) will make future expansions and contributions much easier.

Configuration and Environment Management: Improve how configuration is handled to enhance usability. Leverage the Pydantic settings system to centralize all config parameters (API keys, venue-specific settings, thresholds, fee rates, etc.) with environment variable overrides and a clear .env file example
GitHub
. Each exchange or deployment environment should be configurable without code changes – e.g. one should easily toggle between paper trading and real trading endpoints, adjust global risk limits, or enable/disable certain triangles through config. Implement validation on startup to catch any invalid config values or missing credentials, using Pydantic’s validation features
GitHub
. By having a well-documented configuration layer, new users can set up the system more easily and safely (for instance, providing sample config for common exchanges and describing each setting in documentation).

Robust Testing and QA Processes: As the project grows, institute a comprehensive testing framework to catch bugs and prevent regressions. Begin by writing unit tests for all critical computations (triangular math, profit calculations with fees, position sizing logic, etc.) and for the execution workflow (simulate order fill scenarios, partial fills, error handling)
GitHub
. Use integration tests with mocked exchange APIs to simulate realistic market conditions without risking real funds
GitHub
. Incorporate property-based tests or scenario simulations (e.g. repeatedly simulate an arbitrage cycle with random fills/slippage to ensure the system remains stable). Aim for a high coverage (e.g. 80%+ of code covered by tests) so that refactoring or adding new features (like cross-exchange trades) can be done confidently
GitHub
. A solid QA suite is crucial, especially in finance, to ensure that changes intended to improve profitability do not introduce unseen risks or bugs.

Continuous Integration & Deployment Pipeline: Set up CI/CD to automate quality checks and streamline deployments. For instance, use a GitHub Actions pipeline (or similar) to run the test suite, linters, and type-checkers on every pull request, preventing bad code from being merged
GitHub
. The CI can also build Docker images for the app, embedding all dependencies (including optional WebSocket and DeFi libraries) so that the bot can be deployed reliably in any environment. Prepare a Docker Compose setup for multi-venue operation, as already envisioned, ensuring the container runs with least privilege (non-root user) and can be easily configured via environment variables
GitHub
. Over time, move toward full deployment automation – for example, automated releases or update scripts – to facilitate running the arbitrage bot continuously on a server or cloud instance. The end goal is a one-click or one-command deployment, aligning with the project’s plan for “full containerization and deployment automation” in a production setting
GitHub
.

Monitoring, Metrics, and Alerting: Enhance observability so that you (and any operators) can trust the system’s performance and quickly react to issues. Build out the Prometheus metrics suite to track key performance indicators: number of arbitrage attempts, successful fills, cumulative profit, latency of data updates, order failure counts, etc.
GitHub
. Ensure metrics cover new features (for example, a gauge for each asset’s inventory, a histogram for WebSocket data staleness, and counters for cross-exchange cycle attempts vs. successes). Implement structured logging (in JSON format) that logs each significant event (orders placed, fills, cancellations, errors) with context, without exposing sensitive info
GitHub
. Introduce an alerting mechanism – e.g. integrate a Discord or email webhook to send notifications when something goes wrong (such as a sequence of failed trades triggering a circuit breaker, or an exchange connection dropping)
GitHub
. This level of monitoring not only improves the safety and reliability of the system but also helps in fine-tuning strategy parameters by analyzing metrics over time (for example, to adjust profit thresholds or cooldown periods based on observed data).

Comprehensive Documentation and Runbooks: Expand and refine the documentation to make the system easier to use and maintain. In the README and associated docs, add a safety checklist and clearly document all new features, flags, and configuration options (e.g. how to enable dry-run mode, how to interpret metrics, how to set thresholds)
GitHub
. Include guided examples for common workflows – for instance, a step-by-step example of running in fitness --simulate mode on Kraken, or how to do a small live trial safely
GitHub
GitHub
. Create an operator runbook that covers operational procedures: starting/stopping the bot, using the global kill switch in emergencies, rebalancing funds across exchanges, troubleshooting common errors, and monitoring the Prometheus dashboard
GitHub
. Wherever useful, add screenshots or snippet examples (for metrics output, sample log lines, etc.) to make the documentation more approachable
GitHub
. Clear and thorough documentation will not only improve usability for yourself and any collaborators but will also enforce clarity in the project’s design as it evolves.

Improved CLI and User Experience: Polish the command-line interface to be more user-friendly and self-documenting. Use Typer’s features to provide detailed help text and examples for each command (many of which are already available via --help-verbose) and ensure new commands/flags (for things like multi-venue or cross-exchange mode, dry-run toggles, etc.) are included
GitHub
. For instance, add a global --dry-run flag that applies to all live trading commands to prevent accidental real trades during testing
GitHub
. Enhance the keys:check command to not only verify API keys but also output the exchange’s relevant limits (like min order size, fee rates) and the status of each required trading pair, so users can confirm their environment is correctly set up
GitHub
. Consider quality-of-life improvements such as more informative console logging (e.g. color-coded messages for different events, or summaries at the end of a run) and interactive prompts or confirmations when running potentially risky operations (like going live without a simulate test). By focusing on UX, you make the tool accessible to a wider audience and reduce the chance of user error, which in turn means the arbitrage system can be operated more confidently and effectively.
