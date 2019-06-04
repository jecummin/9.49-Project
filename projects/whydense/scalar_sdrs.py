# ----------------------------------------------------------------------
# Numenta Platform for Intelligent Computing (NuPIC)
# Copyright (C) 2019, Numenta, Inc.  Unless you have an agreement
# with Numenta, Inc., for a separate license for this software code, the
# following terms and conditions apply:
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU Affero Public License for more details.
#
# You should have received a copy of the GNU Affero Public License
# along with this program.  If not, see http://www.gnu.org/licenses.
#
# http://numenta.org/licenses/
# ----------------------------------------------------------------------

"""This code computes, through simulation, the probability of matching two
random scalar sparse vectors. Xw and Xi both have dimensionality n.

A "match" occurs when Xw dot Xi > theta.

We can test probabilities under different initialization conditions for Xi and
Xw, and for different theta's. We can get nice exponential dropoffs with
dimensionality, similar to binary sparse vectors, under the following
conditions:

|Xw|_0 = k
|Xi|_0 = a

Non-zero entries in Xw are uniform in [-1/k, 1/k]
Non-zero entries in Xi are uniform in S*[0, 2/k]

Here Xw is the putative weight vector and Xi is a positive input vector
(positive because presumably it is after a non-linearity such as ReLU or
K-Winners). Theta is defined as mean(Xw dot Xw) / 2.0. We define it this way to
provide a certain amount of invariance to noise in the inputs. A pretty
corrupted version of Xw will still match Xw.

S controls the scale of Xi relative to Xw. By varying S, we can plot the
effect of scaling on the match probabilities.
"""
import time
from multiprocessing import Pool
from os import cpu_count

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import torch
from matplotlib.figure import figaspect

matplotlib.use("Agg")


def get_sparse_tensor(
    num_nonzeros, input_size, output_size, only_positive=False, fixed_range=1.0 / 24
):
    """
    Return a random tensor that is initialized like a weight matrix Size is
    output_size X input_size, where weightSparsity% of each row is non-zero.
    """
    # Initialize weights in the typical fashion.
    w = torch.Tensor(output_size, input_size)

    if only_positive:
        w.data.uniform_(0, fixed_range)
    else:
        w.data.uniform_(-fixed_range, fixed_range)

    # Zero out weights for sparse weight matrices
    if num_nonzeros < input_size:
        num_zeros = input_size - num_nonzeros

        output_indices = np.arange(output_size)
        input_indices = np.array(
            [np.random.permutation(input_size)[:num_zeros] for _ in output_indices],
            dtype=np.long,
        )

        # Create tensor indices for all non-zero weights
        zero_indices = np.empty((output_size, num_zeros, 2), dtype=np.long)
        zero_indices[:, :, 0] = output_indices[:, None]
        zero_indices[:, :, 1] = input_indices
        zero_indices = torch.LongTensor(zero_indices.reshape(-1, 2))

        zero_wts = (zero_indices[:, 0], zero_indices[:, 1])
        w.data[zero_wts] = 0.0

    return w


def get_permuted_tensors(w, kw, n, m2, noise_pct):
    """
    Generate m2 noisy versions of w. Noisy version of w is generated by
    randomly permuting noisePct of the non-zero components to other components.

    :return:
    """
    w2 = w.repeat(m2, 1)
    nz = w[0].nonzero()
    number_to_zero = int(round(noise_pct * kw))
    for i in range(m2):
        indices = np.random.permutation(kw)[0:number_to_zero]
        for j in indices:
            w2[i, nz[j]] = 0
    return w2


def plot_dot(dot, title="Histogram of dot products", path="dot.pdf"):
    bins = np.linspace(dot.min(), dot.max(), 100)
    plt.hist(dot, bins, alpha=0.5, label="All cols")
    plt.title(title)
    plt.xlabel("Dot product")
    plt.ylabel("Number")
    plt.savefig(path)
    plt.close()


def get_theta(k, n_trials=100000):
    """Estimate a reasonable value of theta for this k."""
    the_dots = np.zeros(n_trials)
    w1 = get_sparse_tensor(k, k, n_trials, fixed_range=1.0 / k)
    for i in range(n_trials):
        the_dots[i] = w1[i].dot(w1[i])

    dot_mean = the_dots.mean()
    print(
        "k=",
        k,
        "min/mean/max diag of w dot products",
        the_dots.min(),
        dot_mean,
        the_dots.max(),
    )

    theta = dot_mean / 2.0
    print("Using theta as mean / 2.0 = ", theta)

    return theta, the_dots


def return_matches(kw, kv, n, theta, input_scaling=1.0):
    """
    :param kw: k for the weight vectors
    :param kv: k for the input vectors
    :param n:  dimensionality of input vector
    :param theta: threshold for matching after dot product

    :return: percent that matched, number that matched, total match comparisons
    """
    # How many weight vectors and input vectors to generate at a time
    m1 = 4
    m2 = 1000

    weights = get_sparse_tensor(kw, n, m1, fixed_range=1.0 / kw)

    # Initialize random input vectors using given scaling and see how many match
    input_vectors = get_sparse_tensor(
        kv, n, m2, only_positive=True, fixed_range=2 * input_scaling / kw
    )
    dot = input_vectors.matmul(weights.t())
    num_matches = ((dot >= theta).sum()).item()
    pct_matches = num_matches / float(m1 * m2)

    return pct_matches, num_matches, m1 * m2


def return_false_negatives(kw, noise_pct, n, theta):
    """Generate a weight vector W, with kw non-zero components. Generate 1000
    noisy versions of W and return the match statistics. Noisy version of W is
    generated by randomly setting noisePct of the non-zero components to zero.

    :param kw: k for the weight vectors
    :param noise_pct: percent noise, from 0 to 1
    :param n:  dimensionality of input vector
    :param theta: threshold for matching after dot product

    :return: percent that matched, number that matched, total match comparisons
    """
    w = get_sparse_tensor(kw, n, 1, fixed_range=1.0 / kw)

    # Get permuted versions of W and see how many match
    m2 = 10
    input_vectors = get_permuted_tensors(w, kw, n, m2, noise_pct)
    dot = input_vectors.matmul(w.t())

    num_matches = ((dot >= theta).sum()).item()
    pct_matches = num_matches / float(m2)

    return pct_matches, num_matches, m2


def compute_false_negatives(args):
    n = args["n"]
    kw = args["kw"]
    noise_pct = args["noise_pct"]
    n_trials = args["n_trials"]

    theta, _ = get_theta(kw)

    num_matches = 0
    total_comparisons = 0
    for _ in range(n_trials):
        pct, num, total = return_false_negatives(kw, noise_pct, n, theta)
        num_matches += num
        total_comparisons += total

    pct_false_negatives = 1.0 - float(num_matches) / total_comparisons
    print(
        "kw, n, noise:",
        kw,
        n,
        noise_pct,
        ", matches:",
        num_matches,
        ", comparisons:",
        total_comparisons,
        ", pct false negatives:",
        pct_false_negatives,
    )

    args.update({"pctFalse": pct_false_negatives})

    return args


def compute_false_negatives_parallel(
    listof_noise=(0.1, 0.2, 0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.7, 0.8),
    kw=24,
    num_workers=8,
    n_trials=1000,
    n=500,
):
    print("Computing match probabilities for kw=", kw)

    # Create arguments for the possibilities we want to test
    args = []
    for ni, noise in enumerate(listof_noise):
        args.append(
            {
                "kw": kw,
                "n": n,
                "noise_pct": noise,
                "n_trials": n_trials,
                "error_index": ni,
            }
        )

    num_experiments = len(args)
    if num_workers > 1:
        pool = Pool(processes=num_workers)
        rs = pool.map_async(compute_false_negatives, args, chunksize=1)
        while not rs.ready():
            remaining = rs._number_left
            pct_done = 100.0 - (100.0 * remaining) / num_experiments
            print(
                "    =>",
                remaining,
                "experiments remaining, percent complete=",
                pct_done,
            )
            time.sleep(5)
        pool.close()  # No more work
        pool.join()
        result = rs.get()
    else:
        result = []
        for arg in args:
            result.append(compute_false_negatives(arg))

    # Read out results and store in numpy array for plotting
    errors = np.zeros(len(listof_noise))
    for r in result:
        errors[r["error_index"]] = r["pct_false"]

    print("Errors for kw=", kw)
    print(errors)
    plot_false_matches(
        listof_noise, errors, kw, "scalar_false_matches_kw" + str(kw) + ".pdf"
    )


def compute_match_probability(args):
    """Runs a number of trials of returnMatches() and returns an overall
    probability of matches given the parameters.

    :param args is a dictionary containing the following keys:

    kw: k for the weight vectors

    kv: k for the input vectors. If -1, kv is set to n/2

    n:  dimensionality of input vector

    theta: threshold for matching after dot product

    n_trials: number of trials to run

    inputScaling: scale factor for the input vectors. 1.0 means the scaling
      is the same as the stored weight vectors.

    :return: args updated with the percent that matched
    """
    kv = args["k"]
    n = args["n"]
    kw = args["kw"]
    theta = args["theta"]

    if kv == -1:
        kv = int(round(n / 2.0))

    num_matches = 0
    total_comparisons = 0
    for _ in range(args["n_trials"]):
        pct, num, total = return_matches(kw, kv, n, theta, args["input_scaling"])
        num_matches += num
        total_comparisons += total

    pct_matches = float(num_matches) / total_comparisons
    print(
        "kw, kv, n, s:",
        kw,
        kv,
        n,
        args["input_scaling"],
        ", matches:",
        num_matches,
        ", comparisons:",
        total_comparisons,
        ", pct matches:",
        pct_matches,
    )

    args.update({"pct_matches": pct_matches})

    return args


def compute_match_probability_parallel(args, num_workers=8):
    num_experiments = len(args)
    if num_workers > 1:
        pool = Pool(processes=num_workers)
        rs = pool.map_async(compute_match_probability, args, chunksize=1)
        while not rs.ready():
            remaining = rs._number_left
            pct_done = 100.0 - (100.0 * remaining) / num_experiments
            print(
                "    =>",
                remaining,
                "experiments remaining, percent complete=",
                pct_done,
            )
            time.sleep(5)
        pool.close()  # No more work
        pool.join()
        result = rs.get()
    else:
        result = []
        for arg in args:
            result.append(compute_match_probability(arg))

    return result


def compute_match_probabilities(
    listofk_values=(64, 128, 256, -1),
    listof_n_values=(250, 500, 1000, 1500, 2000, 2500),
    input_scale=1.0,
    kw=24,
    num_workers=10,
    n_trials=1000,
):
    print("Computing match probabilities for input scale=", input_scale)

    # Create arguments for the possibilities we want to test
    args = []
    theta, _ = get_theta(kw)
    for ki, k in enumerate(listofk_values):
        for ni, n in enumerate(listof_n_values):
            args.append(
                {
                    "k": k,
                    "kw": kw,
                    "n": n,
                    "theta": theta,
                    "n_trials": n_trials,
                    "input_scaling": input_scale,
                    "error_index": [ki, ni],
                }
            )

    result = compute_match_probability_parallel(args, num_workers)

    # Read out results and store in numpy array for plotting
    errors = np.zeros((len(listofk_values), len(listof_n_values)))
    for r in result:
        errors[r["error_index"][0], r["error_index"][1]] = r["pct_matches"]

    print("Errors for kw=", kw)
    print(repr(errors))
    plot_matches(listof_n_values, errors, "scalar_effect_of_n_kw" + str(kw) + ".pdf")
    return errors


def compute_scaled_probabilities(
    list_of_scales=(1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0),
    list_of_k_values=(64, 128, 256),
    kw=32,
    n=1000,
    num_workers=10,
    n_trials=1000,
):
    """
    Compute the impact of S on match probabilities for a fixed value of n.
    """
    # Create arguments for the possibilities we want to test
    args = []
    theta, _ = get_theta(kw)
    for ki, k in enumerate(list_of_k_values):
        for si, s in enumerate(list_of_scales):
            args.append(
                {
                    "k": k,
                    "kw": kw,
                    "n": n,
                    "theta": theta,
                    "n_trials": n_trials,
                    "input_scaling": s,
                    "error_index": [ki, si],
                }
            )

    result = compute_match_probability_parallel(args, num_workers)

    errors = np.zeros((len(list_of_k_values), len(list_of_scales)))
    for r in result:
        errors[r["error_index"][0], r["error_index"][1]] = r["pct_matches"]

    print("Errors using scaled inputs, for kw=", kw)
    print(repr(errors))
    plot_scaled_matches(
        list_of_scales, errors, "scalar_effect_of_scale_kw" + str(kw) + ".pdf"
    )
    return errors


def compute_match_probability_omega(k, b_max, theta, n_trials=100):
    """The Omega match probability estimates the probability of matching when
    both vectors have exactly b components in common.  This function computes
    this probability for b=1 to b_max.

    For each value of b this function:

    1) Creates n_trials instances of Xw(b) which are vectors with b components
    where each component is uniform in [-1/k, 1/k].

    2) Creates n_trials instances of Xi(b) which are vectors with b components
    where each component is uniform in [0, 2/k].

    3) Does every possible dot product of Xw(b) dot Xi(b), i.e. n_trials * n_trials
    dot products.

    4) Counts the fraction of cases where Xw(b) dot Xi(b) >= theta

    Returns an array with b_max entries, where each entry contains the
    probability computed in 4).
    """
    omega_prob = np.zeros(b_max + 1)

    for b in range(1, b_max + 1):
        xwb = get_sparse_tensor(b, b, n_trials, fixed_range=1.0 / k)
        xib = get_sparse_tensor(b, b, n_trials, only_positive=True, fixed_range=2.0 / k)
        r = xwb.matmul(xib.t())
        num_matches = ((r >= theta).sum()).item()
        omega_prob[b] = num_matches / float(n_trials * n_trials)

    print(omega_prob)

    return omega_prob


def plot_matches(
    listof_n_values, errors, file_name="scalar_effect_of_n.pdf", fig=None, ax=None
):
    if fig is None:
        fig, ax = plt.subplots()

    fig.suptitle("Probability of matching sparse scalar vectors")
    ax.set_xlabel("Dimensionality (n)")
    ax.set_ylabel("Frequency of matches")
    ax.set_yscale("log")

    ax.plot(
        listof_n_values,
        errors[0, :],
        "k:",
        label="a=64 (predicted)",
        marker="o",
        color="black",
    )
    ax.plot(
        listof_n_values,
        errors[1, :],
        "k:",
        label="a=128 (predicted)",
        marker="o",
        color="black",
    )
    ax.plot(
        listof_n_values,
        errors[2, :],
        "k:",
        label="a=256 (predicted)",
        marker="o",
        color="black",
    )
    ax.plot(
        listof_n_values,
        errors[3, :],
        "k:",
        label="a=n/2 (predicted)",
        marker="o",
        color="black",
    )

    ax.annotate(
        r"$a = 64$",
        xy=(listof_n_values[3] + 100, errors[0, 3]),
        xytext=(-5, 2),
        textcoords="offset points",
        ha="left",
        color="black",
    )
    ax.annotate(
        r"$a = 128$",
        xy=(listof_n_values[3] + 100, errors[1, 3]),
        ha="left",
        color="black",
    )
    ax.annotate(
        r"$a = 256$",
        xy=(listof_n_values[3] + 100, errors[2, 3]),
        ha="left",
        color="black",
    )
    ax.annotate(
        r"$a = \frac{n}{2}$",
        xy=(listof_n_values[3] + 100, errors[3, 3] / 2.0),
        ha="left",
        color="black",
    )

    ax.minorticks_off()
    ax.grid(True, alpha=0.3)

    if file_name is not None:
        plt.savefig(file_name)
        plt.close()


def plot_scaled_matches(
    list_of_scales, errors, file_name="scalar_effect_of_scale.pdf", fig=None, ax=None
):
    if fig is None:
        fig, ax = plt.subplots()

    fig.suptitle("Matching sparse scalar vectors: effect of scale")
    ax.set_xlabel("Scale factor (s)")
    ax.set_ylabel("Frequency of matches")
    ax.set_yscale("log")

    ax.plot(
        list_of_scales,
        errors[0, :],
        "k:",
        label="a=64 (predicted)",
        marker="o",
        color="black",
    )
    ax.plot(
        list_of_scales,
        errors[1, :],
        "k:",
        label="a=128 (predicted)",
        marker="o",
        color="black",
    )
    ax.plot(
        list_of_scales,
        errors[2, :],
        "k:",
        label="a=128 (predicted)",
        marker="o",
        color="black",
    )

    ax.annotate(
        r"$a=64$",
        xy=(list_of_scales[1] + 0.2, errors[0, 1]),
        xytext=(-5, 2),
        textcoords="offset points",
        ha="left",
        color="black",
    )
    ax.annotate(
        r"$a=128$",
        xy=(list_of_scales[1] - 0.1, (2 * errors[1, 1] + errors[1, 2]) / 3.0),
        ha="left",
        color="black",
    )
    ax.annotate(
        r"$a=256$",
        xy=(list_of_scales[1] - 0.1, (errors[2, 1] + errors[2, 2]) / 2.0),
        ha="left",
        color="black",
    )

    ax.minorticks_off()
    ax.grid(True, alpha=0.3)

    if file_name is not None:
        plt.savefig(file_name)
        plt.close()


def plot_theta_distribution(kw, file_name="theta_distribution.pdf"):
    theta, the_dots = get_theta(kw)

    # Plot histogram of overlaps
    bins = np.linspace(float(the_dots.min()), float(the_dots.max()), 50)
    plt.hist(the_dots, bins, alpha=0.5, label="Dot products")
    plt.legend(loc="upper right")
    plt.xlabel("Dot product")
    plt.ylabel("Frequency")
    plt.title("Distribution of dot products, kw=" + str(kw))
    plt.savefig(file_name)
    plt.close()


def plot_false_matches(
    list_of_noise, errors, kw, file_name="scalar_false_positives.pdf"
):
    fig, ax = plt.subplots()

    fig.suptitle("Probability of false negatives with $k_w$=" + str(kw))
    ax.set_xlabel("Pct of components set to zero")
    ax.set_ylabel("Frequency of false negatives")
    # ax.set_yscale("log")

    ax.plot(list_of_noise, errors, "k:", marker="o", color="black")

    plt.minorticks_off()
    plt.grid(True, alpha=0.3)

    plt.savefig(file_name)
    plt.close()


def plot_matches2(
    listof_n_values,
    errors,
    list_of_scales,
    scale_errors,
    file_name="scalar_matches.pdf",
):
    """
    Plot two figures side by side in an aspect ratio appropriate for the paper.
    """
    w, h = figaspect(0.4)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(w, h))

    plot_matches(listof_n_values, errors, file_name=None, fig=fig, ax=ax1)
    plot_scaled_matches(list_of_scales, scale_errors, file_name=None, fig=fig, ax=ax2)

    plt.savefig(file_name)
    plt.close()


def create_pregenerated_graphs():
    """Creates graphs based on previous runs of the scripts.

    Useful for editing graph format for writeups.
    """
    # Graph for computeMatchProbabilities(kw=32, n_trials=3000)
    list_of_n_values = [250, 500, 1000, 1500, 2000, 2500]
    kw = 32
    errors = np.array(
        [
            [
                3.65083333e-03,
                3.06166667e-04,
                1.89166667e-05,
                4.16666667e-06,
                1.50000000e-06,
                9.16666667e-07,
            ],
            [
                2.44633333e-02,
                3.64491667e-03,
                3.16083333e-04,
                6.93333333e-05,
                2.16666667e-05,
                8.66666667e-06,
            ],
            [
                7.61641667e-02,
                2.42496667e-02,
                3.75608333e-03,
                9.78333333e-04,
                3.33250000e-04,
                1.42250000e-04,
            ],
            [
                2.31302500e-02,
                2.38609167e-02,
                2.28072500e-02,
                2.33225000e-02,
                2.30650000e-02,
                2.33988333e-02,
            ],
        ]
    )

    # Graph for computeScaledProbabilities(n_trials=3000)
    list_of_scales = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
    scale_errors = np.array(
        [
            [
                1.94166667e-05,
                1.14900000e-03,
                7.20725000e-03,
                1.92405833e-02,
                3.60794167e-02,
                5.70276667e-02,
                7.88510833e-02,
            ],
            [
                3.12500000e-04,
                7.07616667e-03,
                2.71600000e-02,
                5.72415833e-02,
                8.95497500e-02,
                1.21294333e-01,
                1.50582500e-01,
            ],
            [
                3.97708333e-03,
                3.31468333e-02,
                8.04755833e-02,
                1.28687750e-01,
                1.71220000e-01,
                2.07019250e-01,
                2.34703167e-01,
            ],
        ]
    )

    plot_matches2(
        list_of_n_values,
        errors,
        list_of_scales,
        scale_errors,
        "scalar_matches_kw" + str(kw) + ".pdf",
    )


if __name__ == "__main__":

    # The main graphs (takes about 12-15 mins each)
    if False:
        kw = 32
        list_of_n_values = [250, 500, 1000, 1500, 2000, 2500]
        list_of_k_values = [64, 128, 256, -1]
        list_of_scales = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
        n_trials = 3000

        errors = compute_match_probabilities(
            kw=kw,
            list_of_k_values=list_of_k_values,
            list_of_n_values=list_of_n_values,
            input_scale=1.0,
            num_workers=cpu_count(),
            n_trials=n_trials,
        )

        scale_errors = compute_scaled_probabilities(
            kw=kw,
            list_of_scales=list_of_scales,
            list_of_k_values=list_of_k_values,
            n=1000,
            num_workers=cpu_count(),
            n_trials=n_trials,
        )
        plot_matches2(
            list_of_n_values,
            errors,
            list_of_scales,
            scale_errors,
            "scalar_matches_kw" + str(kw) + ".pdf",
        )
    else:
        # These are graphs using pregenerated numbers for the above
        create_pregenerated_graphs()

    # theta, _ = getTheta(32)
    # computeMatchProbabilityOmega(32.0, 32, theta)

    # computeMatchProbabilities(kw=24, n_trials=1000)
    # computeMatchProbabilities(kw=16, n_trials=3000)
    # computeMatchProbabilities(kw=48, n_trials=3000)
    # computeMatchProbabilities(kw=64, n_trials=3000)
    # computeMatchProbabilities(kw=96, n_trials=3000)

    # plotThetaDistribution(32)

    # computeFalseNegativesParallel(kw=32, n_trials=10000)
    # computeFalseNegativesParallel(kw=64, n_trials=10000)
    # computeFalseNegativesParallel(kw=128, n_trials=10000)