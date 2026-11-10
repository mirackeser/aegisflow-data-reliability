# Engineering workflow

Use English for code, comments, issues, commits, pull requests and active technical documentation. Preserve the original Turkish architecture as a source archive.

Deliver small vertical increments: define the problem and acceptance criteria, implement the smallest coherent capability, test its success and failure paths, inspect the diff, publish a focused pull request and verify CI. Update the backlog and report actual limitations at the end of each increment. Do not equate registered roles with implemented capabilities.

Keep domain logic independent of UI, connectors and model providers. Prefer deterministic checks for policy, identity, budgets and evidence integrity. Use explicit data contracts and bounded inputs. Never place credentials, real enterprise data or generated local state in source control.

Definition of done: observable behavior matches acceptance criteria; meaningful tests pass; installed-package behavior works; documentation and limitations match code; CI succeeds; a reviewer can assess a focused PR. Passing tests do not imply production acceptance or benchmark superiority.

UI work must use restrained typography, consistent spacing, accessible contrast, clear evidence hierarchy and complete loading, empty and failure states. Visual polish must support investigation and decision making. Interface implementation follows functioning data and diagnostic contracts.
