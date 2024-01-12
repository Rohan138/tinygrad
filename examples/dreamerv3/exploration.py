import distributions
import models
import networks
import utils

from tinygrad import Tensor, nn


class Random:
    def __init__(self, config, act_space):
        self._config = config
        self._act_space = act_space

    def actor(self, feat=None):
        if self._config.actor["dist"] == "onehot":
            return distributions.OneHotCategorical(
                Tensor.zeros(int(self._act_space.n))
                .repeat((self._config.num_envs, 1))
                .to(self._config.device)
            )
        else:
            return distributions.Independent(
                distributions.Uniform(
                    Tensor(self._act_space.low)
                    .repeat((self._config.num_envs, 1))
                    .to(self._config.device),
                    Tensor(self._act_space.high)
                    .repeat((self._config.num_envs, 1))
                    .to(self._config.device),
                ),
                1,
            )

    def train(self, start, context, data):
        return None, {}


class Plan2Explore:
    def __init__(self, config, world_model, reward):
        self._config = config
        self._reward = reward
        self._behavior = models.ImagBehavior(config, world_model)
        self.actor = self._behavior.actor
        if config.dyn_discrete:
            feat_size = config.dyn_stoch * config.dyn_discrete + config.dyn_deter
            stoch = config.dyn_stoch * config.dyn_discrete
        else:
            feat_size = config.dyn_stoch + config.dyn_deter
            stoch = config.dyn_stoch
        size = {
            "embed": world_model.embed_size,
            "stoch": stoch,
            "deter": config.dyn_deter,
            "feat": config.dyn_stoch + config.dyn_deter,
        }[self._config.disag_target]
        inp_dim = feat_size + world_model.num_actions if config.disag_action_cond else 0
        kw = dict(
            inp_dim=inp_dim,
            shape=size,
            layers=config.disag_layers,
            units=config.disag_units,
            act=config.act,
        )
        self._networks = [networks.MLP(**kw) for _ in range(config.disag_models)]
        self._expl_opt = utils.Optimizer(
            "explorer",
            self.parameters(),
            config.model_lr,
            config.opt_eps,
            config.grad_clip,
            config.opt,
        )

    def parameters(self):
        return nn.state.get_parameters(self._networks)

    def train(self, start, context, data):
        metrics = {}
        stoch = start["stoch"]
        if self._config.dyn_discrete:
            stoch = Tensor.reshape(
                stoch, (stoch.shape[:-2] + ((stoch.shape[-2] * stoch.shape[-1]),))
            )
        target = {
            "embed": context["embed"],
            "stoch": stoch,
            "deter": start["deter"],
            "feat": context["feat"],
        }[self._config.disag_target]
        inputs = context["feat"]
        if self._config.disag_action_cond:
            inputs = Tensor.cat(
                inputs, Tensor(data["action"]).to(self._config.device), dim=-1
            )
        metrics.update(self._train_ensemble(inputs, target))
        metrics.update(self._behavior._train(start, self._intrinsic_reward)[-1])
        return None, metrics

    def _intrinsic_reward(self, feat, state, action):
        inputs = feat
        if self._config.disag_action_cond:
            inputs = Tensor.cat(inputs, action, dim=-1)
        preds = Tensor.cat(*[head(inputs).mode[None] for head in self._networks], dim=0)
        disag = Tensor.mean(Tensor.std(preds, 0), -1)[..., None]
        if self._config.disag_log:
            disag = Tensor.log(disag)
        reward = self._config.expl_intr_scale * disag
        if self._config.expl_extr_scale:
            reward += self._config.expl_extr_scale * self._reward(feat, state, action)
        return reward

    def _train_ensemble(self, inputs, targets):
        if self._config.disag_offset:
            targets = targets[:, self._config.disag_offset :]
            inputs = inputs[:, : -self._config.disag_offset]
        targets = targets.detach()
        inputs = inputs.detach()
        preds = [head(inputs) for head in self._networks]
        likes = Tensor.cat(
            *[Tensor.mean(pred.log_prob(targets))[None] for pred in preds], dim=0
        )
        loss = -Tensor.mean(likes)
        self._expl_opt.zero_grad()
        loss.backward()
        metrics = self._expl_opt.step()
        return metrics