# stack webapp

Build, run, and deploy webapps

## Synopsis

```bash
stack webapp [OPTIONS] COMMAND [ARGS]...
```

## Description

[Placeholder: Add detailed description of webapp-specific functionality for building and deploying web applications]

## Subcommands

### build

Build the specified webapp container

```bash
stack webapp build [OPTIONS]
```

#### Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--base-container` | TEXT | Base container image to use | - |
| `--source-repo` | TEXT | Directory containing the webapp to build (required) | - |
| `--force-rebuild` | FLAG | Override dependency checking -- always rebuild | False |
| `--extra-build-args` | TEXT | Supply extra arguments to build | - |
| `--tag` | TEXT | Container tag | `bozemanpass/<app_name>:stack` |

### deploy

Create a deployment for the specified webapp container

```bash
stack webapp deploy [OPTIONS]
```

#### Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--kube-config` | TEXT | Provide a config file for a k8s deployment | - |
| `--image-registry` | TEXT | Container image registry URL (required for k8s) | - |
| `--deployment-dir` | TEXT | Create deployment files in this directory (required) | - |
| `--image` | TEXT | Image to deploy (required) | - |
| `--url` | TEXT | URL to serve (required for k8s) | - |
| `--config-file` | TEXT | Environment file for webapp | - |

### run

Run the specified webapp container

```bash
stack webapp run [OPTIONS]
```

#### Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--image` | TEXT | Image to deploy (required) | - |
| `--config-file` | TEXT | Environment file for webapp | - |
| `--port` | INTEGER | Port to use | Random |

## Webapp Types

Supported webapp frameworks:
- React
- Vue.js
- Angular
- Next.js
- Static HTML
- Node.js applications
- Python Flask/Django
- [Placeholder: Add other supported frameworks]

## Build Process

1. Analyze source repository
2. Detect framework type
3. Install dependencies
4. Build production assets
5. Create optimized container
6. Tag image appropriately

## Examples

### Building Webapps

```bash
# Build a webapp from source
stack webapp build --source-repo ./my-react-app

# Build with custom base image
stack webapp build --source-repo ./my-app --base-container node:18-alpine

# Force rebuild
stack webapp build --source-repo ./my-app --force-rebuild

# Build with custom tag
stack webapp build --source-repo ./my-app --tag myregistry/myapp:v1.0
```

### Running Webapps

```bash
# Run a webapp locally
stack webapp run --image myapp:latest

# Run with specific port
stack webapp run --image myapp:latest --port 3000

# Run with environment file
stack webapp run --image myapp:latest --config-file .env.local
```

### Deploying Webapps

```bash
# Deploy to Docker
stack webapp deploy \
  --image myapp:latest \
  --deployment-dir ~/deployments/myapp

# Deploy to Kubernetes
stack webapp deploy \
  --image myapp:latest \
  --deployment-dir ~/deployments/myapp \
  --kube-config ~/.kube/config \
  --image-registry registry.example.com \
  --url https://myapp.example.com

# Deploy with configuration
stack webapp deploy \
  --image myapp:latest \
  --deployment-dir ~/deployments/myapp \
  --config-file production.env
```

## Environment Configuration

Environment files (`.env` format):
```env
NODE_ENV=production
API_URL=https://api.example.com
DATABASE_URL=postgres://...
```

## See Also

- [stack build](build.md) - Build stack components
- [stack deploy](deploy.md) - Deploy a stack
- [stack manage](manage.md) - Manage a deployed stack
