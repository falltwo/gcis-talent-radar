"""Offline demonstration: python -X utf8 -m recruitment.demo."""
from pathlib import Path
from tempfile import TemporaryDirectory

from recruitment.auth import Principal
from recruitment.models import Requirement, SimulationCreate
from recruitment.service import RecruitmentService


def main():
    print("104模擬刊登展示：僅使用暫存資料庫，不連線104、不建立真實職缺。")
    principal = Principal("demo-tenant", "demo-hr", "hr")
    with TemporaryDirectory(prefix="recruitment-demo-") as folder:
        service = RecruitmentService(Path(folder) / "demo.sqlite")
        for scenario in ("SUCCESS", "FAILURE"):
            print("\n展示情境：" + scenario)
            request = service.requirement(principal, Requirement(
                title="【模擬示範，非真實職缺】CNC操作員", district="大雅區", shift="日班",
                headcount=3, required_skills=["cnc"], salary_min=35000, salary_max=45000,
            ))
            service.approve(principal, request["id"], request["revision"])
            row = service.create_simulation(principal, request["id"], SimulationCreate(idempotency_key=scenario, scenario=scenario))
            print(row["status_label"])
            row = service.approve_simulation(principal, row["id"])
            print(row["status_label"])
            row = service.complete_simulation(principal, row["id"])
            print(row["status_label"])
            print("sent_to_platform =", row["sent_to_platform"])


if __name__ == "__main__":
    main()
