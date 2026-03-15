from __future__ import annotations

from typing import Any

from analyst.macro_data import MacroDataClient, coerce_macro_data_client


class MacroDataOperationHandler:
    def __init__(
        self,
        operation: str,
        *,
        data_client: MacroDataClient | None = None,
        store: Any | None = None,
        retriever: Any | None = None,
    ) -> None:
        self._operation = operation
        self._client = coerce_macro_data_client(
            data_client=data_client,
            store=store,
            retriever=retriever,
        )

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._client.invoke(self._operation, arguments)
