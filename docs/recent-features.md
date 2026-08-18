# Recent New Features

  - [#266](https://github.com/bozemanpass/stack/pull/266) [Stack integrity checking](./stack-integrity.md): `stack validate` verifies a stack's files agree with each other, and the same checks run advisorily during `prepare`, `build` and `init`
  - [#260](https://github.com/bozemanpass/stack/pull/260) `stack manage … update` converges a running deployment onto changed images and configuration, recreating only the services that changed
  - [#256](https://github.com/bozemanpass/stack/pull/256) [Secrets](./secrets.md): stacks declare which environment variables are secret; values are generated at deploy time or pulled from a reference (`env:`/`file:`/`exec:`), and never land in git, the spec, or `config.env`
  - [#244](https://github.com/bozemanpass/stack/pull/244) [Scheduled backup & restore](./backup.md): encrypted restic backups of a deployment's volumes to any S3-compatible store, with `stack manage … backup now | list | restore`, restorable across targets and into new deployments
  - [#174](https://github.com/bozemanpass/stack/pull/174) Image identity anchored at the recipe repo: tags are the recipe repo's commit hash, `stack.lock` (superseding `wrapper.lock`) pins source and wrapper inputs, and unpinned/uncommitted builds get unpublishable `stackdev-` tags
  - [#163](https://github.com/bozemanpass/stack/pull/163) Prebuilt wrapper base images pulled from ghcr; `wrapper-ref` pinning and `wrapper.lock` for repeatable wrapped builds
  - [#161](https://github.com/bozemanpass/stack/pull/161) Deploy wrapped repositories (e.g. pure static HTML) directly from a stack via the `wrapper` field in stack.yml
  - [#160](https://github.com/bozemanpass/stack/pull/160) Generic [container wrappers](./wrappers.md), discoverable from external repositories; static content hosting with nginx
  - [#100](https://github.com/bozemanpass/stack/pull/100) TLS support for Docker http ingress
  - [#88](https://github.com/bozemanpass/stack/pull/88) Automatic HTTP ingress/reverse proxying for Docker (for small demo/production deployments without the need to host on k8s)
  - [#87](https://github.com/bozemanpass/stack/pull/87) Shell command line completion
  - [#86](https://github.com/bozemanpass/stack/pull/86) Output [Mermaid](https://www.mermaidchart.com/) charts for a stack
  - [#76](https://github.com/bozemanpass/stack/pull/76) Stack checklist pre-flight command (confirms stack components are available to deploy)
  - [#48](https://github.com/bozemanpass/stack/pull/48) Simplified configuration via config file
  - [#23](https://github.com/bozemanpass/stack/pull/23) Stack composition (a stack can contain other stacks)
  - [#11](https://github.com/bozemanpass/stack/pull/11) Container images defined by git repositories (GitRev)
  
