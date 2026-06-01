## 🔴 强制步骤0.5：每次skill_manage后自动验证门
每次使用 `skill_manage(action='patch')` 或 `skill_manage(action='edit')` 后，
**立即执行**：
```bash
python3 ~/.hermes/scripts/skillopt_trainer.py validate <skill_name>
```
验证门不通过（score < 阈值）→ **回退修改，不能接受低质量skill**
