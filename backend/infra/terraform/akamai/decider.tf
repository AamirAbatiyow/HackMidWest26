# Strands Decider 2B: a small CPU decision model for agentic workflows.
# https://github.com/strands-labs/strands-decider (Apache-2.0)
#
# Deployed in the model subnet alongside the risk model. The Decider makes routing
# decisions (email format, parser tool selection) without seeing payment amounts.
# It runs on CPU; the 2B model needs ~4.5 GB for weights and fits in 16 GB RAM.

resource "linode_firewall" "decider" {
  count           = var.enable_decider ? 1 : 0
  label           = "${local.name}-fw-decider"
  inbound_policy  = "DROP"
  outbound_policy = "ACCEPT"
  tags            = local.tags

  inbound {
    label    = "decider-from-app-subnet"
    action   = "ACCEPT"
    protocol = "TCP"
    ports    = tostring(var.decider_port)
    ipv4     = [var.vpc_cidrs.ingress]
  }

  inbound {
    label    = "ssh-from-app-subnet"
    action   = "ACCEPT"
    protocol = "TCP"
    ports    = "22"
    ipv4     = [var.vpc_cidrs.ingress]
  }

  linodes = [linode_instance.decider[0].id]
}

resource "linode_instance" "decider" {
  count           = var.enable_decider ? 1 : 0
  label           = "${local.name}-decider"
  region          = var.region
  type            = var.decider_type
  image           = var.image
  authorized_keys = var.ssh_public_keys
  tags            = local.tags
  private_ip      = false

  metadata {
    user_data = base64encode(templatefile("${path.module}/cloud-init-decider.yaml.tftpl", {
      decider_model = var.decider_model
      decider_port  = var.decider_port
      proxy_url     = "http://${local.proxy_ip}:${var.proxy_port}"
    }))
  }

  interface {
    purpose   = "vpc"
    primary   = true
    subnet_id = linode_vpc_subnet.model.id
    ipv4 {
      vpc = var.decider_vpc_ip
    }
  }
}
