#!/usr/bin/env python
"""
Implementation of a Variational Recurrent Autoencoder (https://arxiv.org/abs/1412.6581), a Variational Autoencoder (https://arxiv.org/abs/1606.05908) with recurrent Neural Networks as encoder and decoder.
The aim of this project is to obtain similar results to https://arxiv.org/abs/1511.06349 (Generating sentences from a continous space).

__author__ = "Valentin Lievin, DTU, Denmark"
__copyright__ = "Copyright 2017, Valentin Lievin"
__credits__ = ["Valentin Lievin"]
__license__ = "GPL"
__version__ = "1.0.1"
__maintainer__ = "Valentin Lievin"
__email__ = "valentin.lievin@gmail.com"
__status__ = "Development"
"""    
import tensorflow as tf

class Vrae:
    def __init__(self, state_size, num_layers, latent_dim, batch_size, num_symbols, input_keep_prob,output_keep_prob, latent_loss_weight, dtype_precision, cell_type):
        """
        Initi Variational Recurrent Autoencoder (VRAE) for sequences. The model clears the current tf graph and implements this model as the new graph. 
        Args:
            state_size (Natural Integer): size of the states of the RNN cells (encoder and decoder)
            num_layers (Natural Integer): number of layers in the RNN cells
            latent_dim (Natural Integer): dimension of the latent space
            batch_size (Natural Integer): batch size
            num_symbols (Natural Integer): number of symbols in the data (number of unique characters if used with characters or vocabulary size if used with words)
            input_keep_prob (float): dropout keep probability for the inputs
            output_keep_prob (float): dropout keep probability for the outputs
            latent_loss_weight (float): weight used to weaken the regularization/latent loss
            dtype_precision (Integer): dtype precision
            cell_type (string): type of cell: LSTM,GRU,LNLSTM
        Returns 
        """
        if dtype_precision==16:
            dtype = tf.float16
        else:
            dtype = tf.float32
        # clear the default graph
        tf.reset_default_graph()
        self.batch_size = batch_size
        # placeholders
        self.input_keep_prob_value = input_keep_prob
        self.output_keep_prob_value = output_keep_prob
        self.x_input = tf.placeholder( tf.int32, [batch_size, None], name='input_placeholder')
        self.x_input_lenghts = tf.placeholder(shape=(batch_size,), dtype=tf.int32, name='encoder_inputs_length')
        self.weights_input = tf.placeholder( tf.int32, [batch_size, None], name='weights_placeholder')
        self.input_keep_prob = tf.placeholder(dtype,name="input_keep_prob")
        self.output_keep_prob = tf.placeholder(dtype,name="output_keep_prob")
        self.max_sentence_size = tf.reduce_max(self.x_input_lenghts )
        with tf.name_scope("training_parameters"):
            self.B = tf.placeholder(dtype, name='Beta_deterministic_warmup')
            self.learning_rate = tf.placeholder(dtype, shape=[], name='learning_rate')
            self.epoch = tf.placeholder(dtype, shape=[], name='epoch')
        # summaries
        tf.summary.scalar("Beta", self.B)
        tf.summary.scalar("learning_rate", self.learning_rate)
        tf.summary.scalar("epoch", self.epoch)
        tf.summary.scalar("sentences max length", self.max_sentence_size)
        # prepare the input
        with tf.name_scope("input_transformations"):
            inputs_onehot = tf.one_hot(self.x_input, num_symbols, axis= -1, dtype=dtype)   # one hot encoding
            data_dim = int(inputs_onehot.shape[2])
            rnn_inputs = tf.reverse(inputs_onehot, [1])   # reverse input
        
        # encoder
        encoder_output = encoder(state_size, num_layers, rnn_inputs, dtype,cell_type, self.input_keep_prob, self.output_keep_prob, scope="encoder")     
        # stochastic layer
        self.z, self.z_mu, self.z_ls2 = stochasticLayer(encoder_output, latent_dim, batch_size,
                                                        dtype, scope="stochastic_layer")
        # decoder
        self.decoder_output = decoder(self.z, batch_size, state_size, num_layers, 
                                      data_dim, self.x_input_lenghts, dtype, cell_type, 
                                      self.input_keep_prob, self.output_keep_prob, scope="decoder") 
        # loss
        self.loss = loss_function(self.decoder_output, self.x_input, 
                                  self.weights_input,self.z_ls2, self.z_mu, 
                                  self.B, latent_loss_weight, dtype, scope="loss") 
        # optimizer
        self.optimizer = optimizationOperation(self.loss, self.learning_rate, scope="optimizer")   # optimizer
        # merge summaries: summarize variables
        self.merged_summary = tf.summary.merge_all()
    
    def step(self, sess, padded_batch_xs, beta, learning_rate, batch_lengths, batch_weights, epoch) :
        """ 
        train the model for one step
        Args:
            sess: current Tensorflow session
            padded_batch_xs: padded input batch
            beta: beta parameter for deterministic warmup
            learning_rate: learning rate (potentially controled during training)
            batch_lengths: sentences lengths 
            batch_weights: sentences weights
            epoch: current epoch
        Returns:
            a tuple of values:
                optimizer op
                current loss
                summary op
        """
        return sess.run([self.optimizer, self.loss, self.merged_summary, self.max_sentence_size ], feed_dict={self.x_input: padded_batch_xs, 
                                                           self.B:beta, 
                                                           self.learning_rate: learning_rate,
                                                           self.x_input_lenghts:batch_lengths,
                                                           self.weights_input: batch_weights,
                                                           self.input_keep_prob:self.input_keep_prob_value, 
                                                           self.output_keep_prob:self.output_keep_prob_value,
                                                           self.epoch: epoch
                                                            })
    
    def reconstruct(self, sess, padded_batch_xs, batch_lengths, batch_weights):
        """
        Feed a batch of inputs and reconstruct it
        Args:
            sess: current Tensorflow session
            padded_batch_xs: padded input batch
            batch_lengths: sentences lengths 
        Returns:
            tuple x_reconstruct,z_vals,z_mean_val,z_log_sigma_sq_val, sequence_loss
                x_reconstruct: reconstruction of the input
                z_vals: sampled values of z (prior)
                z_mean_val: mean_z values of the prior
                z_log_sigma_sq_val: log of sigma^2 of the prior
                sequence_loss: average cross entropy
        """
        return sess.run((self.decoder_output,self.z, self.z_mu, self.z_ls2, self.loss), feed_dict={self.x_input: padded_batch_xs,self.x_input_lenghts:batch_lengths,self.weights_input: batch_weights, self.B: 1,self.input_keep_prob:1, self.output_keep_prob:1})
    
    def zToX(self,sess,z_sample,s_length):
        """
        Reconstruct X from a latent variable z.
        Args:
            sess: current Tensorflow session
            z_sample (numpy array): z sample, array of dimension (latent_dim x1)
            s_length: sentence_length
        Returns:
            x generated from z 
        """
        s_lengths = [s_length for _ in xrange(self.batch_size)]
        z_samples = [z_sample for _ in xrange(self.batch_size)]
        return sess.run((self.decoder_output), feed_dict={self.z: z_samples,self.x_input_lenghts:s_lengths,self.input_keep_prob:1, self.output_keep_prob:1})
    
    def XToz(self,sess,x_sample):
        """
        Project X to the latent space Z
        Args:
            sess: current Tensorflow session
            x_sample: sequence (list of Integers)
        Returns:
            x generated from z 
        """
        x_samples = [x_sample for _ in xrange(self.batch_size)]
        return sess.run((self.z_mu), feed_dict={self.x_input: x_samples ,self.input_keep_prob:1, self.output_keep_prob:1})
    
    
def encoder(state_size, num_layers, rnn_inputs, dtype, cell_type, input_keep_prob, output_keep_prob, scope="encoder"):
    """
    Encoder of the VRAE model. It corresponds to the approximation of p(z|x), thus encodes the inputs x into a higher level representation z. The encoder is Dynamic Recurrent Neural Network which takes a batch of sequence of arbitray lengths as inputs. The output is the last state of the last cell and corresponds to a representation of the whole input.
    Args:
        state_size (Natural Integer): state size for the RNN cell
        num_layers (Natural Integer): number of layers for the the RNN cell
        rnn_inputs (Tensor): input tensor (batch_size x None x input_dimension)
        dtype (string): dtype
        input_keep_prob (float): dropout keep probability for the inputs
        output_keep_prob (float): dropout keep probability for the outputs
        scope (string): scope name
    Returns:
            (Tensor) the last state of the RNN, dimension (batch_size x state_size)
    """
    with tf.name_scope(scope):
        with tf.variable_scope('encoder_cell'):
            if cell_type == 'GRU':
                cell_fn = tf.contrib.rnn.GRUCell
            elif cell_type == 'LSTM':
                cell_fn = tf.contrib.rnn.LSTMCell
            elif cell_type == 'LNLSTM':
                cell_fn = tf.contrib.rnn.LayerNormBasicLSTMCell
            
            cells = []
            for _ in range(2 * num_layers):
                cell = cell_fn(state_size)
                cell = tf.contrib.rnn.DropoutWrapper( cell, output_keep_prob=output_keep_prob, input_keep_prob=input_keep_prob)
                cells.append(cell)
            cell_fw = tf.contrib.rnn.MultiRNNCell( cells[:num_layers] )
            cell_bw = tf.contrib.rnn.MultiRNNCell( cells[num_layers:] )
            rnn_outputs, final_state = tf.nn.bidirectional_dynamic_rnn(cell_fw, cell_bw, rnn_inputs, dtype=dtype, scope="Encoder_rnn")
        if cell_type == 'LSTM':
            final_state = tf.concat([ state[num_layers-1][0] for state in final_state] , 1)
        else:
            final_state = tf.concat([ state[num_layers-1] for state in final_state] , 1)
        return final_state


def stochasticLayer(encoder_output, latent_dim, batch_size,dtype, scope="stochastic_layer"):
    """
    The stochastic layer represents the prior distribution Z. We choose to model the prior as a Gaussian distribution with parameters mu and sigma. The distribution is represented by these two parameters only (mu and sigma) as introduced by https://arxiv.org/abs/1312.6114. Then we can draw samples epsilon from a normal distribution N(0,1) and obtain the samples z = mu + epsilon * sigma from the prior. This is what we call the "reparametrization trick" and allows us to train the model using SGD.
    Args:
        encoder_output (Tensor): input tensor (batch_size x encoder_state_size)
        latent_dim (Natural Integer): dimension of the latent space
        batch_size (Natural Integer): batch length
        scope (string): scope name
    Returns:
        A tuple z,z_mu,z_ls2:
            z: samples drawn from the prior
            z_mu: tensor representing 
    """
    with tf.name_scope(scope):
        # reparametrization trick
        with tf.name_scope("Z"):
            z_mu = tf.contrib.layers.fully_connected( inputs=encoder_output,num_outputs=latent_dim, activation_fn=None, scope="z_mu" ) 
            z_ls2 = tf.contrib.layers.fully_connected( inputs=encoder_output,num_outputs=latent_dim, activation_fn=None, scope="z_ls2" ) 
            
        # sample z from the latent distribution
        with tf.name_scope("z_samples"):
            with tf.name_scope('random_normal_sample'):
                eps = tf.random_normal((batch_size, latent_dim), 0, 1, dtype=dtype) # draw a random number
            with tf.name_scope('z_sample'):
                z = tf.add(z_mu, tf.multiply(tf.sqrt(tf.exp(z_ls2)), eps))  # a sample it from Z -> z
        # summaries
        tf.summary.histogram("z_mu", z_mu)
        tf.summary.histogram("z_ls2", z_ls2)
        tf.summary.histogram("z", z)
        
        return z,z_mu,z_ls2


def dynamic_rnn_with_projection_layer( cell_dec, z_input, x_input_lenghts, W_proj, b_proj, batch_size, state_size, data_dim, dtype, scope="dynamic_rnn_with_projection_layer"):
    """
    A custom dynamic rnn implemented using the raw_rnn class from Tensorflow. The difference with the dynamic_rnn is the use of a projection layer to feed the true output value to the next step. Indeed, for each cell, the output is a tensor of size (batch_size x state_size). Here we project this output into the expected output value, thus we obtain a Tensor (batch_size x data_dim). Then we output this expected output to the next cell. This makes the model more robust.
    Args:
        cell_dec (tf.nn.rnn_cell): RNN cell
        z_input (Tensor): input Tensor of size (batch_size x state_size) Typically the samples z projected to the dimension of the decoder
        x_input_lengths (Tensor): a Tensor of integers of size (batch_size, ). Lenght of the input sequences.
        W_proj (tf.Variable): weights of the projection layer.
        b_proj (tf.Variable): biases of the projection layer.
        batch_size (Natural Integer): batch size.
        state_size (Natural Integer): RNN cell state size.
        data_dim (Natural Integer): dimension of the data.
        dtype (string): dtype to be used   
        scope (string): scope name
    """
    with tf.name_scope(scope):
        def loop_fn(time, cell_output, cell_state, loop_state):
            emit_output = cell_output  # == None for time == 0
            prev_out = cell_output
            elements_finished = (time >= x_input_lenghts) # array or bool
            finished = tf.reduce_all(elements_finished) # check if all elements finished and get a single boolean
            if cell_output is None:  # time == 0
                next_cell_state = cell_dec.zero_state(batch_size, dtype)
                next_input_value = tf.concat([z_input, tf.zeros([batch_size,data_dim], dtype=dtype)], 1) 
            else:
                #emit_output = tf.add(tf.matmul(W_proj,prev_out), b_proj)
                next_cell_state = cell_state
                next_input_value = tf.cond( # removing this condition leads to the read TensorArray problem: used for dynamic rray
                    finished,
                    lambda:tf.concat([ tf.zeros([batch_size,state_size], dtype=dtype),  tf.add(tf.matmul(prev_out, W_proj), b_proj)], 1) ,
                    lambda:tf.concat([z_input, tf.add(tf.matmul(prev_out, W_proj), b_proj) ], 1) )
            next_input = tf.cond(
                finished,
                lambda: tf.zeros([batch_size, data_dim + state_size], dtype=dtype),
                lambda: next_input_value )
            next_loop_state = None
            return (elements_finished, next_input, next_cell_state,
                    emit_output, next_loop_state)
        return tf.nn.raw_rnn(cell_dec, loop_fn)#, parallel_iterations = 1)


def decoder(z, batch_size, state_size, num_layers, data_dim, x_input_lenghts, dtype, cell_type, input_keep_prob, output_keep_prob, scope="decoder"):
    """"
    Decoder of the VRAE model. This neural network approximates the posterior distribution p(x|z). The decoder transforms samples z from the prior distribution to a reconstruction of x.
    Args:
        z (Tensor): samples z from the prior distribution (batch_size x latent_dim)
        batch_size (Natural Integer): batch size
        state_size (Natural Integer): size of the RNN cell
        num_layers (Natural Integer): number of layers in the RNN cell
        data_dim (Natural Integer): dimension of the data
        x_input_lenghts (Tensor): lengths of the inputs (batch_len, )
        dtype (string): dtype to be used
        cell_type (string): type of RNN cell
        input_keep_prob (float): dropout keep probability for the inputs
        output_keep_prob (float): dropout keep probability for the outputs
        scope (string): scope name
    Returns:
        A tensor of size (batch_size x None x data_dim) which is a reconstruction of x
    """
    with tf.name_scope(scope):
        # projection layer
        with tf.name_scope("projection_layer"):
            W_proj = tf.Variable(tf.random_uniform([state_size, data_dim], 0, 1, dtype=dtype), dtype=dtype)
            b_proj = tf.Variable(tf.zeros([data_dim], dtype=dtype), dtype=dtype)
        # connect z to the RNN
        h_z2dec = tf.contrib.layers.fully_connected(z, state_size, scope="z2initial_decoder_state", activation_fn=None)
        # RNN Cell
        if cell_type == 'GRU':
            cell_fn = tf.contrib.rnn.GRUCell
        elif cell_type == 'LSTM':
            cell_fn = tf.contrib.rnn.LSTMCell
        elif cell_type == 'LNLSTM':
            cell_fn = tf.contrib.rnn.LayerNormBasicLSTMCell
        cells = []
        for _ in range(num_layers):
            cell = cell_fn(state_size)
            cell = tf.contrib.rnn.DropoutWrapper( cell, output_keep_prob=output_keep_prob, input_keep_prob=input_keep_prob)
            cells.append(cell)
        dec_cell = tf.contrib.rnn.MultiRNNCell(cells)                                 
        # RNN decoder
        outputs_ta, final_state, _ = dynamic_rnn_with_projection_layer( dec_cell, h_z2dec, x_input_lenghts, W_proj, b_proj, batch_size, state_size, data_dim, dtype, scope="dynamic_rnn_with_projection_layer")
         # project the output
        rnn_outputs_decoder = outputs_ta.stack()
        decoder_max_steps, decoder_batch_size, decoder_dim = tf.unstack(tf.shape(rnn_outputs_decoder))
        decoder_outputs_flat = tf.reshape(rnn_outputs_decoder, (-1, state_size))
        decoder_logits_flat = tf.add(tf.matmul(decoder_outputs_flat, W_proj), b_proj)
        rnn_outputs_decoder = tf.transpose( tf.reshape(decoder_logits_flat, (decoder_max_steps, batch_size, data_dim)) , [1,0,2])
        return rnn_outputs_decoder
                    

def sentence_loss(x_reconstr_mean, x_input, weights_input, dtype, scope="sentence_loss"):
    """
    Sentence loss based on tf.contrib.seq2seq.sequence_loss. This is an reduced element-wise cross entropy.
    Args:
        x_reconstr_mean (Tensor): reconstruction of the input (batch_len x None x data_dim)
        x_input (Tensor): model input (batch_len x None x data_dim)
        weights_input (Tensor): model input weights (batch_len x None). A list of integer to indicate if 
            the current element is a real element (1) or a element added for padding (0).
        dtype (string): dtype
        scope (string): scope name
    Returns:
        Reconstruction loss (Variable)
    """
    with tf.name_scope(scope):
        return tf.contrib.seq2seq.sequence_loss(x_reconstr_mean, x_input, tf.cast( weights_input, dtype) )
                    
def latent_loss_function(z_ls2, z_mu, scope="latent_loss"):
    """
    Latent loss. Acts as a regularization and shape the prior distribution as normal distribution N(0,1). This is used to limit the capacity of the latent distribution and push the model to optimize its content by placing similar items close to another.
    Args:
        z_ls2 (Tensor): log of the squarred value of sigma, a parameter which controls the prior distribution
        z_mu (Tensor): value of mu, a parameter which controls the prior distribution
        scope (string): scope name
    Returns: 
        Latent loss (Variable)
    """
    with tf.name_scope(scope):
        return -0.5 * tf.reduce_sum(1 + z_ls2 - tf.square(z_mu) - tf.exp(z_ls2), 1)
        
def loss_function(x_reconstr_mean, x_input, weights_input,z_ls2, z_mu, B, latent_loss_weight, dtype, scope="loss"):
    """
    Loss function of the VRAE model: reconstruction loss + Beta * latent_loss_weight * latent_loss.
    Args:
        x_reconstr_mean (Tensor): reconstruction of the input (batch_len x None x data_dim)
        x_input (Tensor): model input (batch_len x None x data_dim)
        weights_input (Tensor): model input weights (batch_len x None). A list of integer to indicate if 
            the current element is a real element (1) or a element added for padding (0).
        z_ls2 (Tensor): log of the squarred value of sigma, a parameter which controls the prior distribution
        z_mu (Tensor): value of mu, a parameter which controls the prior distribution
        B (Placeholder): value of Beta used for the deterministic warm-up
        latent_loss_weight (float): weight used to weaken the latent_loss and help the model to optimize the reconstruction
        dtype (string): dtype
        scope (string): scope name
    Returns:
        loss of the VRAE model 
    """
    with tf.name_scope(scope):
        reconstruction_loss = sentence_loss(x_reconstr_mean, x_input, weights_input, dtype)
        latent_loss = latent_loss_function(z_ls2, z_mu) # L2 regularization
        #l2 = 0.00001 * sum(
        #    tf.nn.l2_loss(tf_var)
        #        for tf_var in tf.trainable_variables()
        #        if not ("noreg" in tf_var.name or "Bias" in tf_var.name)
        #)
        loss = tf.reduce_mean(reconstruction_loss + B * latent_loss_weight * latent_loss )
        # summaries
        tf.summary.scalar("reconstruction_loss", reconstruction_loss)
        tf.summary.scalar("latent_loss", tf.reduce_mean(latent_loss) )
        tf.summary.scalar("loss", loss)
        return loss
                    
def optimizationOperation(cost, learning_rate, scope="training_step"):
    """
    optimizationStep
    Args:
        cost: loss function
        learning_rate (float or placeholder): learning rate
    Returns:
        Tensorflow optimizer
    """
    with tf.variable_scope(tf.get_variable_scope(), reuse=False):
        with tf.name_scope('train_step'):
            return tf.train.AdamOptimizer(learning_rate).minimize(cost)
        