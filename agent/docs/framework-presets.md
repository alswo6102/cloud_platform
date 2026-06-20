# Framework Deployment Presets

Framework presets hide common Docker build details and expose container port
`3000` by default.

| Preset | Behavior |
| --- | --- |
| `existing` | Use the repository root Dockerfile |
| `vite` | Build with Node and serve `dist` through Nginx |
| `react` | Build with Node and serve `build` through Nginx |
| `nextjs` | Build and run Next.js with `next start` |
| `express` | Install Node dependencies and run `npm start` |
| `fastapi` | Run `main:app` or `app:app` through Uvicorn |
| `flask` | Run `app:app` through Gunicorn |
| `django` | Detect the WSGI module and run Gunicorn |
| `spring-maven` | Build a JAR with Maven and run Java |
| `spring-gradle` | Build a JAR with Gradle and run Java |
| `go` | Build a static Go binary and run it |

Preset Dockerfiles are generated only inside the server clone. They do not
modify the source GitHub repository.

The deployment request may include environment variable names, but never
secret values. Configure actual values through the dashboard environment
dialog after deployment.
