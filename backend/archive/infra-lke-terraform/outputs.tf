output "instance_public_ip" {
  value = var.use_lke ? null : tolist(linode_instance.app[0].ipv4)[0]
}

output "public_url" {
  description = "Give this to the frontend as its API base URL."
  value       = length(linode_nodebalancer.app) > 0 ? "http://${linode_nodebalancer.app[0].ipv4}" : null
}

output "object_storage_endpoint" {
  value = "https://${linode_object_storage_bucket.artifacts.s3_endpoint}"
}

output "object_storage_bucket" {
  value = linode_object_storage_bucket.artifacts.label
}

output "object_storage_access_key" {
  value     = linode_object_storage_key.app.access_key
  sensitive = true
}

output "object_storage_secret_key" {
  value     = linode_object_storage_key.app.secret_key
  sensitive = true
}

output "database_url" {
  description = "terraform output -raw database_url > put it in the server's .env as DATABASE_URL"
  sensitive   = true
  value = var.enable_postgres ? format(
    "postgresql+psycopg://%s:%s@%s:%d/defaultdb?sslmode=require",
    linode_database_postgresql_v2.main[0].root_username,
    linode_database_postgresql_v2.main[0].root_password,
    linode_database_postgresql_v2.main[0].host_primary,
    linode_database_postgresql_v2.main[0].port,
  ) : null
}

output "kubeconfig" {
  description = "terraform output -raw kubeconfig | base64 -d > ~/.kube/hackmw.yaml"
  value       = var.use_lke ? linode_lke_cluster.main[0].kubeconfig : null
  sensitive   = true
}
