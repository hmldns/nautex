"""Document Service for handling document operations."""

import os
import logging
from typing import List, Optional, Dict
from pathlib import Path
import aiofiles

from ..api.api_models import Document
from ..api.scope_context_model import DocumentsMeta
from ..services.nautex_api_service import NautexAPIService
from ..services.config_service import ConfigurationService
from ..services.docs_meta import DocsSyncMeta, needs_refetch

# Set up logging
logger = logging.getLogger(__name__)


class DocumentService:
    """Service for handling document operations."""

    def __init__(
        self,
        nautex_api_service: NautexAPIService,
        config_service: ConfigurationService
    ):
        """Initialize the document service.

        Args:
            nautex_api_service: The Nautex API service
            config_service: The configuration service
        """
        self.nautex_api_service = nautex_api_service
        self.config_service = config_service
        logger.debug("DocumentService initialized")

    async def get_document(self, project_id: str, doc_designator: str) -> Optional[Document]:
        """Get a document by designator.

        Args:
            project_id: The ID of the project
            doc_designator: The designator of the document

        Returns:
            A Document object, or None if the document was not found
        """
        try:
            return await self.nautex_api_service.get_document_tree(project_id, doc_designator)
        except Exception as e:
            logger.error(f"Error getting document {doc_designator}: {e}")
            return None

    async def save_document_to_file(self, document: Document, output_path: Path) -> tuple[bool, str]:
        """Save a document to a file.

        Args:
            document: The document to save
            output_path: The path to save the document to

        Returns:
            Tuple of (success, path or error message)
        """
        try:
            # Create directory if it doesn't exist
            os.makedirs(output_path.parent, exist_ok=True)

            # Generate markdown content
            # FIXME, introduce doc trees types
            if document.designator.startswith("FILE"):
                content_str = document.render_tree()
            else:
                content_str = document.render_markdown()

            # Write to file
            async with aiofiles.open(output_path, 'w') as f:
                await f.write(content_str)

            logger.debug(f"Document {document.designator} saved to {output_path}")
            return True, str(output_path)
        except Exception as e:
            error_msg = f"Error saving document {document.designator} to {output_path}: {e}"
            logger.error(error_msg)
            return False, error_msg

    async def ensure_documents(
        self,
        project_id: str,
        doc_designators: List[str],
        documents_meta: Optional[DocumentsMeta] = None,
    ) -> Dict[str, str]:
        """Ensure documents are available locally.

        Args:
            project_id: The ID of the project
            doc_designators: List of document designators to ensure
            documents_meta: Server-provided designator → last-update timestamp map.
                When present, unchanged documents are skipped based on the sync
                metafile; when None (older backend), every document is fetched.

        Returns:
            Dictionary mapping document designators to file paths or error messages
        """
        results = {}
        documents_path = Path(self.config_service.documents_path)

        # Create documents directory if it doesn't exist
        os.makedirs(documents_path, exist_ok=True)

        meta = DocsSyncMeta.load(documents_path)

        # Process each document
        for designator in doc_designators:
            try:
                output_filename = f"{designator}.md"
                output_path = documents_path / output_filename

                if documents_meta is not None:
                    refetch, reason = needs_refetch(
                        meta.get(designator), documents_meta.get(designator), output_path,
                    )
                    if not refetch:
                        logger.debug(f"Document {designator} is up to date, skipping fetch")
                        results[designator] = str(output_path)
                        continue
                    logger.debug(f"Document {designator} needs refetch: {reason.value}")

                # Get document from API
                document = await self.get_document(project_id, designator)

                if document:
                    # Save document to file
                    success, result = await self.save_document_to_file(document, output_path)
                    results[designator] = result
                    if success:
                        # Server-authoritative timestamp: doc response first, scope meta as fallback
                        meta.record_sync(
                            designator,
                            updated_at=document.updated_at or (documents_meta or {}).get(designator),
                            path=output_filename,
                        )
                else:
                    error_msg = f"Document {designator} not found"
                    logger.warning(error_msg)
                    results[designator] = error_msg
            except Exception as e:
                error_msg = f"Error ensuring document {designator}: {e}"
                logger.error(error_msg)
                results[designator] = error_msg

        meta.save()
        return results

    async def ensure_plan_dependency_documents(
        self,
        project_id: str,
        plan_id: str,
        documents_meta: Optional[DocumentsMeta] = None,
    ) -> Dict[str, str]:
        """Ensure all dependency documents for a plan are available locally.

        Args:
            project_id: The ID of the project
            plan_id: The ID of the implementation plan
            documents_meta: Server-provided designator → timestamp map from the scope
                response. When present, its keys are the dependency document list
                (skips the plan fetch) and unchanged documents are not re-fetched.

        Returns:
            Dictionary mapping document designators to file paths or error messages, or empty dict if plan not found
        """
        try:
            if documents_meta is not None:
                dependency_docs = list(documents_meta.keys())
                if not dependency_docs:
                    logger.info(f"No dependency documents found for plan {plan_id}")
                    return {}
                logger.info(f"Syncing {len(dependency_docs)} dependency documents for plan {plan_id}")
                return await self.ensure_documents(
                    project_id, dependency_docs, documents_meta=documents_meta,
                )

            # Older backend without documents_meta: resolve the dependency list via the plan
            plan = await self.nautex_api_service.get_implementation_plan(project_id, plan_id)

            if not plan:
                error_msg = f"Implementation plan {plan_id} not found for project {project_id}"
                logger.warning(error_msg)
                return {}

            # Get dependency documents
            dependency_docs = plan.dependency_documents or []

            if not dependency_docs:
                logger.info(f"No dependency documents found for plan {plan_id}")
                return {}

            logger.info(f"Ensuring {len(dependency_docs)} dependency documents for plan {plan_id}")

            # Ensure all dependency documents are available locally
            return await self.ensure_documents(project_id, dependency_docs)

        except Exception as e:
            error_msg = f"Error ensuring dependency documents for plan {plan_id}: {e}"
            logger.error(error_msg)
            return {}
