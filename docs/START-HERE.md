# Before this lab: build the platform in a sensible order

Why keep code in Git? Reviewed configuration makes changes explainable and rebuilds repeatable. Genuine GitOps also needs an automatic pull/reconciliation loop; a one-shot CI deployment does not continuously repair drift.

Start with local networking, trusted time, an administrative recovery path and bootstrap DNS. Bring up local GitLab independently of Kubernetes. Then import reviewed code into your own **private home GitLab** projects using CLI tools, set repository owners, and add scoped runners. Review Terraform plans before protected manual applies. Build Kubernetes, add optional Rancher, then configure KAS/agent access and namespace-scoped workload deployment. Introduce Flyway schema changes and LGTM observability with backup, retention and recovery checks. Add Flux reconciliation only when controller ownership and pruning behavior are understood.

Public example repositories contain generic teaching values; your private home GitLab owns your actual configuration. Neither should contain passwords, private keys, agent tokens, kubeconfigs, Terraform state or unseal shares. Credentials belong in protected runtime/secret-manager paths. Git revert does not restore database data or deleted storage.

Read the [complete series guide](https://github.com/RayEvelyn/homelab-gitops-guide#readme) for clone links, bootstrap order and the reasons behind each repository.
