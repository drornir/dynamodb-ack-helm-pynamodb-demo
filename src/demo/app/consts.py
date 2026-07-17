# Prefixing AWS-side table names keeps them unique across stacks/envs that share one
# AWS account. It's stripped back off when deriving the (already namespaced) k8s object
# name -- see scripts/gen_ack_tables._k8s_resource_name.
TABLES_PREFIX = "demo-"
