#!/usr/bin/env python3
"""
Quick deployment script for Legalassist-AI to Kubernetes
Supports: AWS EKS, Google GKE, Azure AKS
"""

import argparse
import subprocess
import sys
import os
from pathlib import Path


class KubernetesDeployer:
    def __init__(self, namespace: str, environment: str, provider: str):
        self.namespace = namespace
        self.environment = environment
        self.provider = provider
        self.root_dir = Path(__file__).parent
        self.helm_dir = self.root_dir / "k8s" / "helm" / "legalassist-ai"
    
    def run_command(self, cmd: list, check: bool = True) -> str:
        """Run shell command and return output"""
        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, check=check)
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return result.stdout
    
    def check_prerequisites(self):
        """Verify required tools are installed"""
        tools = ["kubectl", "helm", "docker"]
        for tool in tools:
            result = self.run_command(["which", tool], check=False)
            if not result.strip():
                print(f"ERROR: {tool} is not installed")
                sys.exit(1)
    
    def build_image(self, image_tag: str) -> str:
        """Build Docker image"""
        print(f"🔨 Building Docker image: {image_tag}")
        self.run_command(["docker", "build", "-t", image_tag, "."])
        return image_tag
    
    def push_image(self, image_tag: str):
        """Push image to registry based on provider"""
        print(f"📤 Pushing image to registry: {image_tag}")
        
        if self.provider == "aws":
            # AWS ECR
            account_id = self.run_command(
                ["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"]
            ).strip()
            region = os.getenv("AWS_REGION", "us-east-1")
            
            login_cmd = f"aws ecr get-login-password --region {region} | docker login --username AWS --password-stdin {account_id}.dkr.ecr.{region}.amazonaws.com"
            self.run_command(["bash", "-c", login_cmd])
            
            ecr_image = f"{account_id}.dkr.ecr.{region}.amazonaws.com/{image_tag}"
            self.run_command(["docker", "tag", image_tag, ecr_image])
            self.run_command(["docker", "push", ecr_image])
            return ecr_image
        
        elif self.provider == "gcp":
            # Google Container Registry
            project_id = self.run_command(
                ["gcloud", "config", "get-value", "project"]
            ).strip()
            self.run_command(["gcloud", "auth", "configure-docker"])
            
            gcr_image = f"gcr.io/{project_id}/{image_tag}"
            self.run_command(["docker", "tag", image_tag, gcr_image])
            self.run_command(["docker", "push", gcr_image])
            return gcr_image
        
        elif self.provider == "azure":
            # Azure Container Registry
            registry = os.getenv("ACR_REGISTRY_NAME", "legalassistregistry")
            self.run_command(["az", "acr", "login", "--name", registry])
            
            acr_image = f"{registry}.azurecr.io/{image_tag}"
            self.run_command(["docker", "tag", image_tag, acr_image])
            self.run_command(["docker", "push", acr_image])
            return acr_image
        
        else:
            raise ValueError(f"Unknown provider: {self.provider}")
    
    def create_namespace(self):
        """Create Kubernetes namespace if it doesn't exist"""
        print(f"📦 Creating namespace: {self.namespace}")
        self.run_command(
            ["kubectl", "create", "namespace", self.namespace],
            check=False
        )
    
    def deploy_helm_chart(self, image_tag: str):
        """Deploy using Helm"""
        print(f"🚀 Deploying with Helm to {self.environment}")
        
        values_file = self.helm_dir / f"values-{self.environment}.yaml"
        if not values_file.exists():
            print(f"ERROR: Values file not found: {values_file}")
            sys.exit(1)
        
        cmd = [
            "helm", "upgrade", "--install", "legalassist", 
            str(self.helm_dir),
            "--namespace", self.namespace,
            "--values", str(values_file),
            "--set", f"image.tag={image_tag}",
            "--wait",
            "--timeout", "10m"
        ]
        
        self.run_command(cmd)
    
    def verify_deployment(self):
        """Verify deployment is healthy"""
        print("✅ Verifying deployment...")
        
        # Check rollout status
        self.run_command([
            "kubectl", "rollout", "status", "deployment/legalassist",
            "-n", self.namespace,
            "--timeout", "5m"
        ])
        
        # Check pod status
        print("\nPod status:")
        self.run_command([
            "kubectl", "get", "pods", "-n", self.namespace,
            "-l", "app.kubernetes.io/name=legalassist-ai"
        ])
        
        # Check service
        print("\nService status:")
        self.run_command([
            "kubectl", "get", "svc", "-n", self.namespace
        ])
    
    def deploy(self, image_tag: str):
        """Execute full deployment"""
        print(f"🎯 Starting deployment to {self.environment}")
        print(f"   Provider: {self.provider}")
        print(f"   Namespace: {self.namespace}")
        print(f"   Image: {image_tag}\n")
        
        self.check_prerequisites()
        self.create_namespace()
        self.build_image(image_tag)
        image_tag = self.push_image(image_tag)
        self.deploy_helm_chart(image_tag)
        self.verify_deployment()
        
        print(f"\n✨ Deployment to {self.environment} complete!")
        print(f"\nAccess your application:")
        print(f"   kubectl port-forward svc/legalassist 8501:8501 -n {self.namespace}")


def main():
    parser = argparse.ArgumentParser(description="Deploy Legalassist-AI to Kubernetes")
    parser.add_argument(
        "--environment",
        choices=["staging", "production"],
        default="staging",
        help="Deployment environment"
    )
    parser.add_argument(
        "--provider",
        choices=["aws", "gcp", "azure"],
        default="aws",
        help="Cloud provider"
    )
    parser.add_argument(
        "--namespace",
        default=None,
        help="Kubernetes namespace (defaults to environment name)"
    )
    parser.add_argument(
        "--image-tag",
        default=None,
        help="Image tag to use (defaults to git commit hash)"
    )
    
    args = parser.parse_args()
    
    namespace = args.namespace or args.environment
    
    if not args.image_tag:
        # Get commit hash
        commit_hash = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True
        ).stdout.strip()
        image_tag = f"legalassist-ai:{commit_hash}"
    else:
        image_tag = args.image_tag
    
    deployer = KubernetesDeployer(namespace, args.environment, args.provider)
    deployer.deploy(image_tag)


if __name__ == "__main__":
    main()
