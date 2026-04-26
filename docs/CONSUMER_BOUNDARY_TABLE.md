# Consumer Boundary Table

| Concern | Belongs in Diego | Belongs in consumer | Must not enter Diego |
| --- | --- | --- | --- |
| content generation | yes | no | no |
| section/block draft output | yes | projection only | no |
| markdown formatting | no | yes | yes as Diego-owned truth |
| document compile/export | no | no | yes |
| grading semantics for item-based artifacts | no | yes when needed | yes as Diego-owned mode |
| graph editor semantics | no | yes when needed | yes |
| source-binding UI semantics | no | yes | yes |
| refine anchor UI semantics | no | yes | yes |
| shell orchestration semantics | no | yes | yes |
| host workflow naming | no | yes | yes |
| artifact persistence and formal state | no | yes or another authority | yes |

## Boundary Reading

Diego should stably emit generation truth.
Consumers may translate that truth into local artifact forms.
Diego should not absorb host-specific workflow, editor, compile, export, or formal artifact responsibilities.
