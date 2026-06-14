from .base import TaskBase
from env.tasks.utils.obs_check import *
from env.tasks.utils.init_task import *


class Combat(TaskBase):
    # 阅读重点：击杀任务不只看 obs，还通过 InitTaskProxy 查询 C# Mod 里的怪物击杀统计。
    # 因此 benchmark runtime 需要同时持有 task 和 task_proxy。
    def evaluate(self, obs, proxy: InitTaskProxy) -> dict:
        if self.last_obs is None:
            self.last_obs = obs
            if self.evaluator == "kill":
                self.last_count = proxy.get_monster_kills(self.object)
            return {
                "completed": False,
                "quantity": 0,
            }

        if self.evaluator == "kill":
            kill_stat = proxy.get_monster_kills(self.object)
            self.quantity_change = kill_stat - self.last_count
            self.last_count = kill_stat

        elif self.evaluator == "skill":
            self.quantity_change = obs["player"]["skills"]["combat"] - self.last_obs["player"]["skills"]["combat"]

        elif self.evaluator == "profession":
            self.check_list = [self.object]
            self.quantity_change = count_check(self.check_list, obs["player"]["professions"],
                                               self.last_obs["player"]["professions"], False,
                                               "profession")

        self.last_obs = obs
        self.current_quantity += self.quantity_change
        if self.current_quantity >= self.quantity:
            completed = True
        else:
            completed = False

        return {
            "completed": completed,
            "quantity": self.current_quantity,
        }
