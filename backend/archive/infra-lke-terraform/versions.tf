terraform {
  required_version = ">= 1.6"
  required_providers {
    linode = {
      source  = "linode/linode"
      version = "~> 3.0"
    }
  }
  # TODO(optional): remote state in Akamai Object Storage via the s3 backend. Local state is fine for a hackathon.
}

# Auth: export LINODE_TOKEN=... (never put it in tfvars that get committed).
provider "linode" {}
