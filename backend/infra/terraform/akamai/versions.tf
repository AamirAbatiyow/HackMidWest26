terraform {
  required_version = ">= 1.6"
  required_providers {
    linode = {
      source  = "linode/linode"
      version = "~> 3.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
  # Local state for the hackathon (terraform.tfstate is gitignored). For a team, point this at the
  # Object Storage bucket with the s3 backend once the bucket exists.
}

# Auth: `make deploy-akamai` passes LINODE_TOKEN from the environment as TF_VAR_linode_token.
# The provider also reads LINODE_TOKEN directly; the variable exists so plans can run with a dummy value.
provider "linode" {
  token = var.linode_token != "" ? var.linode_token : null
}
