output "public_url" {
  description = "API base URL for the frontend (VITE_API_URL). Self-signed TLS unless tls_cert_pem was supplied."
  value       = local.public_url
}

output "nodebalancer_hostname" {
  value = linode_nodebalancer.ingress.hostname
}

output "nodebalancer_ipv4" {
  value = linode_nodebalancer.ingress.ipv4
}

output "app_public_ips" {
  description = "SSH targets for deploy_akamai.sh (root@<ip>); the API port itself is only open to the NodeBalancer."
  value       = [for i in linode_instance.app : tolist(i.ipv4)[0]]
}

output "app_vpc_ips" {
  value = local.app_ips
}

output "model_vpc_ip" {
  description = "Private model server (reach it via `ssh -J root@<app ip> root@<this>`)."
  value       = var.model_vpc_ip
}

output "decider_vpc_ip" {
  description = "Private Decider server (reach it via `ssh -J root@<app ip> root@<this>`)."
  value       = var.enable_decider ? var.decider_vpc_ip : null
}

output "decider_url" {
  description = "Private URL for DECIDER_URL environment variable (set on the app Linodes)."
  value       = var.enable_decider ? "http://${var.decider_vpc_ip}:${var.decider_port}" : null
}

output "vpc_id" {
  value = linode_vpc.main.id
}

output "subnets" {
  value = {
    ingress = linode_vpc_subnet.ingress.ipv4
    model   = linode_vpc_subnet.model.ipv4
    data    = linode_vpc_subnet.data.ipv4
  }
}

output "firewalls" {
  value = {
    app          = linode_firewall.app.label
    model        = linode_firewall.model.label
    decider      = var.enable_decider ? linode_firewall.decider[0].label : null
    nodebalancer = linode_firewall.nodebalancer.label
  }
}

output "object_storage_endpoint" {
  value = "https://${linode_object_storage_bucket.attachments.s3_endpoint}"
}

output "object_storage_bucket" {
  value = linode_object_storage_bucket.attachments.label
}

output "database_host" {
  value = var.enable_postgres ? linode_database_postgresql_v2.main[0].host_primary : null
}

output "database_url" {
  description = "terraform output -raw database_url (already written to the app Linodes by cloud-init)."
  value       = local.database_url
  sensitive   = true
}

output "tls_self_signed" {
  value = length(tls_self_signed_cert.nb) > 0
}

output "next_steps" {
  value = <<-EOT
    1. make verify-akamai host=${local.public_url}        (health, roles, payments, red-team, TLS)
    2. frontend: VITE_API_URL=${local.public_url} npm run build
    3. secrets were pushed by deploy_akamai.sh; rotate with: infra/scripts/deploy_akamai.sh --secrets-only
    4. tear down: make destroy-akamai
  EOT
}
