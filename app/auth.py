"""ロール定義(職能 × 拠点 マトリクス)。

LLM のシステムプロンプトにアクセス可能 DB / 拠点を埋め込むことで、
MCP の手前でアプリ層フィルタを実現する。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Role:
    key: str
    label: str
    factory_ids: tuple[int, ...]            # 空タプルは「全拠点」を意味する
    allowed_databases: tuple[str, ...]
    description: str

    @property
    def is_all_factories(self) -> bool:
        return len(self.factory_ids) == 0


ALL_DATABASES: tuple[str, ...] = (
    "ebom_db",
    "procurement_db",
    "scada_db",
    "wms_db",
    "qms_db",
)


ROLES: dict[str, Role] = {
    "tokyo_designer": Role(
        key="tokyo_designer",
        label="Tokyo - 設計者",
        factory_ids=(1,),
        allowed_databases=("ebom_db", "scada_db", "qms_db"),
        description="東京拠点の設計部品表(E-BOM)を扱い、必要に応じてSCADAとQMSを参照できる",
    ),
    "tokyo_buyer": Role(
        key="tokyo_buyer",
        label="Tokyo - 購買担当",
        factory_ids=(1,),
        allowed_databases=("procurement_db", "ebom_db", "wms_db"),
        description="東京拠点の購買業務を扱い、E-BOMと在庫を参照できる",
    ),
    "tokyo_operator": Role(
        key="tokyo_operator",
        label="Tokyo - 現場オペレーター",
        factory_ids=(1,),
        allowed_databases=("scada_db", "wms_db"),
        description="東京拠点の設備稼働状況と在庫を参照できる",
    ),
    "osaka_designer": Role(
        key="osaka_designer",
        label="Osaka - 設計者",
        factory_ids=(2,),
        allowed_databases=("ebom_db", "scada_db", "qms_db"),
        description="大阪拠点の設計部品表を扱い、必要に応じてSCADAとQMSを参照できる",
    ),
    "osaka_buyer": Role(
        key="osaka_buyer",
        label="Osaka - 購買担当",
        factory_ids=(2,),
        allowed_databases=("procurement_db", "ebom_db", "wms_db"),
        description="大阪拠点の購買業務を扱い、E-BOMと在庫を参照できる",
    ),
    "osaka_operator": Role(
        key="osaka_operator",
        label="Osaka - 現場オペレーター",
        factory_ids=(2,),
        allowed_databases=("scada_db", "wms_db"),
        description="大阪拠点の設備稼働状況と在庫を参照できる",
    ),
    "quality_manager": Role(
        key="quality_manager",
        label="品質マネージャー(全社)",
        factory_ids=(),
        allowed_databases=("qms_db", "scada_db", "ebom_db"),
        description="全社の品質指標を横断的に分析できる",
    ),
    "admin": Role(
        key="admin",
        label="管理者(全社)",
        factory_ids=(),
        allowed_databases=ALL_DATABASES,
        description="全 DB / 全拠点にアクセス可能",
    ),
}


def get_role(key: str) -> Role:
    if key not in ROLES:
        raise ValueError(f"unknown role: {key}")
    return ROLES[key]
