locals {
  name = var.prefix
  tags = ["hackmidwest", var.prefix]
}

# --- Network --------------------------------------------------------------------------------------

resource "linode_vpc" "main" {
  label       = "${local.name}-vpc"
  region      = var.region
  description = "HackMidwest ${local.name}"
}

resource "linode_vpc_subnet" "app" {
  vpc_id = linode_vpc.main.id
  label  = "app"
  ipv4   = var.vpc_subnet_cidr
}

resource "linode_firewall" "app" {
  count           = var.use_lke ? 0 : 1
  label           = "${local.name}-fw"
  inbound_policy  = "DROP"
  outbound_policy = "ACCEPT"
  tags            = local.tags

  dynamic "inbound" {
    for_each = length(var.admin_cidrs) > 0 ? [1] : []
    content {
      label    = "ssh-admin"
      action   = "ACCEPT"
      protocol = "TCP"
      ports    = "22"
      ipv4     = var.admin_cidrs
    }
  }

  inbound {
    label    = "apps-from-vpc"
    action   = "ACCEPT"
    protocol = "TCP"
    ports    = "8100-8299"
    ipv4     = [var.vpc_subnet_cidr]
  }

  # TODO: if you skip the NodeBalancer, open the API port publicly here instead (demo only).
  linodes = [linode_instance.app[0].id]
}

# --- Compute: single instance (default) -----------------------------------------------------------

resource "linode_instance" "app" {
  count           = var.use_lke ? 0 : 1
  label           = "${local.name}-app"
  region          = var.region
  type            = var.instance_type
  image           = "linode/ubuntu24.04"
  authorized_keys = var.ssh_public_keys
  tags            = local.tags

  metadata {
    user_data = base64encode(templatefile("${path.module}/cloud-init.yaml", { repo_url = var.repo_url }))
  }

  interface {
    purpose = "public"
  }

  interface {
    purpose   = "vpc"
    subnet_id = linode_vpc_subnet.app.id
    ipv4 {
      vpc = var.instance_vpc_ip
    }
  }
}

# --- NodeBalancer (public entry point -> instance over the VPC) -----------------------------------

resource "linode_nodebalancer" "app" {
  count  = !var.use_lke && var.enable_nodebalancer ? 1 : 0
  label  = "${local.name}-nb"
  region = var.region
  tags   = local.tags
  vpcs = [{
    subnet_id = linode_vpc_subnet.app.id
  }]
}

resource "linode_nodebalancer_config" "http" {
  count           = length(linode_nodebalancer.app)
  nodebalancer_id = linode_nodebalancer.app[0].id
  port            = 80
  protocol        = "http"
  algorithm       = "roundrobin"
  check           = "http"
  check_path      = "/health"
  check_interval  = 10
  check_timeout   = 5
  check_attempts  = 3
  # TODO: add a port-443 config with ssl_cert/ssl_key (or put Cloudflare/Akamai CDN in front) if the frontend needs HTTPS.
}

resource "linode_nodebalancer_node" "app" {
  count           = length(linode_nodebalancer.app)
  nodebalancer_id = linode_nodebalancer.app[0].id
  config_id       = linode_nodebalancer_config.http[0].id
  label           = "${local.name}-app"
  address         = "${var.instance_vpc_ip}:${var.api_port}"
  subnet_id       = linode_vpc_subnet.app.id
  weight          = 100
}

# --- Kubernetes: LKE (use_lke = true) -------------------------------------------------------------
# Services of type LoadBalancer get a NodeBalancer automatically via the Linode CCM.

resource "linode_lke_cluster" "main" {
  count       = var.use_lke ? 1 : 0
  label       = "${local.name}-lke"
  region      = var.region
  k8s_version = var.lke_k8s_version
  tags        = local.tags

  pool {
    type  = var.lke_node_type
    count = var.lke_node_count
    # TODO: attach a Cloud Firewall (firewall_id) that keeps LKE's required ports open.
  }
}

# --- Object Storage (models, uploads, agent sessions) ---------------------------------------------

resource "linode_object_storage_bucket" "artifacts" {
  label  = var.bucket_label
  region = var.object_storage_region
}

resource "linode_object_storage_key" "app" {
  label = "${local.name}-app"
  bucket_access {
    bucket_name = linode_object_storage_bucket.artifacts.label
    region      = var.object_storage_region
    permissions = "read_write"
  }
}

# --- Managed Postgres (optional) ------------------------------------------------------------------

resource "linode_database_postgresql_v2" "main" {
  count        = var.enable_postgres ? 1 : 0
  label        = "${local.name}-pg"
  engine_id    = var.postgres_engine
  region       = var.region
  type         = var.postgres_type
  cluster_size = 1
  allow_list   = [var.vpc_subnet_cidr]

  private_network = {
    vpc_id        = linode_vpc.main.id
    subnet_id     = linode_vpc_subnet.app.id
    public_access = false
  }
  # pgvector: run `CREATE EXTENSION IF NOT EXISTS vector;` once (hm_storage.enable_pgvector()).
}
